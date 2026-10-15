"""Passages to facts, with the extract model.

The model reads one passage with its document title and the lists of known areas, teams and people, and returns
facts as `{subject, predicate, value, text}` through a structured output. Nothing it returns is trusted as is:

- the predicate must be in the closed vocabulary, and the subject and value must have the shape it allows;
- area, team and person keys must be ones the graph already knows; unknown keys drop the fact;
- topic keys are normalised and merged, so the same topic from different pages lands on one key.

Each fact starts to hold on its document's date (an RFC's on the day it was accepted, a comment or chat message on
the day it was written) and carries its source's authority. Extraction is the expensive step, so it runs only on
passages likely to carry facts, and every model answer is cached on disk by the passage text and model: a second run
over unchanged pages costs nothing.

- **Pages** (handbook, docs, wiki, team pages, decision records): passages that name a team, an area, a person or a
  process.
- **Conversations** (tickets and chats: issues, pull requests, comment threads, discussions, forum and Slack
  threads): most of what people say there is a question or a bug report, so only passages with a signal are sent: a
  decision ("we decided", "going forward", "deprecated", "moved to"), an ownership statement, or a process or policy
  word, ranked higher when someone the graph knows said it. They come within a per-run budget, so a busy chat
  never crowds out the pages.
"""

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from canon.extract.predicates import AUTHORITY, PREDICATES, SHAPES, merge_topics, normalise_topic
from canon.sources.connector import KIND_GROUPS
from canon.types import Batch, Doc, Fact, Passage

# Pages someone keeps up to date, and conversations: what someone said on a day (tickets and chats).
CONVERSATIONS = KIND_GROUPS["tickets"] + KIND_GROUPS["chats"]
PAGE_KINDS = tuple(k for g in ("docs", "decisions", "structure") for k in KIND_GROUPS[g] if k != "ownership_map")
EXTRACT_KINDS = PAGE_KINDS + CONVERSATIONS
MAX_PHRASE = 160


@dataclass(frozen=True)
class Entities:
    """The areas, teams and people the graph knows, as `key -> display name`."""

    areas: Mapping[str, str]
    teams: Mapping[str, str]
    people: Mapping[str, str]

    @classmethod
    def from_batch(cls, batch: Batch) -> "Entities":
        return cls(
            areas={a.slug: a.name for a in batch.areas},
            teams={t.slug: t.name for t in batch.teams},
            # People known only by name count when they speak in the batch (a Slack member), not otherwise.
            people={
                p.handle: p.name
                for p in batch.people
                if not p.handle.startswith("name:") or p.handle in {x.author for x in batch.passages if x.author}
            },
        )

    def known(self, prefix: str, key: str) -> bool:
        table = {"area": self.areas, "team": self.teams, "person": self.people}.get(prefix)
        return table is not None and key in table


# Input and output dollars per million tokens (Haiku at its price for prompts of 100K tokens or fewer).
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    passages_with_facts: int = 0
    skipped: int = 0  # passages not sent because the model stopped answering
    stopped: str | None = None  # why it stopped
    dropped: dict[str, int] = field(default_factory=dict)

    def cost_usd(self, model: str = "claude-sonnet-5-5") -> float:
        """At list prices per million tokens: cache reads 0.1x input, 5-minute cache writes 1.25x."""
        input_per_mtok, output_per_mtok = PRICES.get(model, PRICES["claude-sonnet-5-5"])
        return (
            self.input_tokens * input_per_mtok
            + self.cache_read_tokens * input_per_mtok * 0.1
            + self.cache_write_tokens * input_per_mtok * 1.25
            + self.output_tokens * output_per_mtok
        ) / 1e6


# ----- choosing passages -----------------------------------------------------------------------------------------

_OWNERSHIP = re.compile(r"\b(own(s|ed|er|ers|ership)?|responsib\w*|in charge of|maintain(s|ed)?)\b", re.I)
_PROCESS = re.compile(
    r"\b(process|policy|policies|rules?|must|always|never|required?|approv\w*|deploy\w*|on[- ]call|rotation|"
    r"escalat\w*|contact|ask|decid\w*|decision|leads?|we use|use[sd]?|tools?|review\w*|support hero)\b",
    re.I,
)


class Mentions:
    """Finds which known teams, areas and people a passage names."""

    def __init__(self, entities: Entities):
        def pattern(names: Iterable[str]) -> re.Pattern | None:
            names = sorted({n for n in names if len(n) >= 4}, key=len, reverse=True)
            return re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.I) if names else None

        self.teams = pattern([*entities.teams.values(), *(s.replace("-", " ") for s in entities.teams)])
        self.areas = pattern(entities.areas.values())
        self.people = pattern([*entities.people.values(), *entities.people])

    def score(self, text: str, kind: str) -> int:
        """0 means not worth a model call. Higher means more likely to carry a fact we can check."""
        team = bool(self.teams and self.teams.search(text)) or bool(re.search(r"\bteam\b", text, re.I))
        area = bool(self.areas and self.areas.search(text))
        person = bool(self.people and self.people.search(text))
        owns = bool(_OWNERSHIP.search(text))
        process = bool(_PROCESS.search(text))
        if not (team or area or person or process):
            return 0
        # Ownership statements first: they are what the ownership map can confirm or show to be out of date.
        return 5 * (owns and (team or area)) + 2 * team + area + person + process


# What people say in a conversation that is worth a model call: a decision or a change, who owns something now, or
# a rule. Questions, bug reports and thanks have none of these.
_DECIDED = re.compile(
    r"\b(we('ve| have)? (decided|agreed|chosen|settled)|decided (to|that|on|against|not)|the decision|going forward|"
    r"from now on|moving forward|deprecat\w*|moved (it |this |them |everything )?(to|into|over)|moving (it |this )?to|"
    r"migrat(e|ed|ing) (to|from|away)|switch(ed|ing)? (over )?to|replaced (it |this )?(with|by)|in favou?r of|"
    r"no longer|sunset\w*|end of life|we('ll| will) (now|stop|start|no longer|move|only|use)|is now (owned|handled|"
    r"maintained|run|managed)|now owns?|took over|taking over|handed (it |this )?over)\b",
    re.I,
)
_RULE = re.compile(
    r"\b(policy|policies|must|is required|are required|not allowed|always|never|the process|our process|on[- ]call|"
    r"escalat\w*|approval|approved by|sign[- ]off|rotation)\b",
    re.I,
)
MIN_TALK = 60  # characters of what was said, after the speaker line


def _said(text: str) -> str:
    """A conversation passage without its speaker line (`"alice, 2026-05-06:"`), which names a person every time."""
    first, sep, rest = text.partition("\n")
    return rest if sep and re.search(r", \d{4}-\d{2}-\d{2}:$", first) else text


def conversation_score(mentions: "Mentions", passage: Passage, known: Mapping[str, str]) -> int:
    """0 means not worth a model call. A decision or a change in what is done counts most; an ownership statement
    about a known team or area next; a rule only when it is about one. Words from someone the graph knows (staff,
    a contributor, a Slack member) rank higher than a stranger's."""
    text = _said(passage.text)
    if len(text) < MIN_TALK:
        return 0
    decided = {m.group(0).lower() for m in _DECIDED.finditer(text)}
    team = bool(mentions.teams and mentions.teams.search(text)) or bool(re.search(r"\bteam\b", text, re.I))
    area = bool(mentions.areas and mentions.areas.search(text))
    owns = bool(_OWNERSHIP.search(text)) and (team or area)
    rule = bool(_RULE.search(text)) and (team or area)
    if not (decided or owns or rule):
        return 0
    known_speaker = bool(passage.author) and (passage.author in known or passage.author.startswith("name:"))
    return 4 * bool(decided) + min(len(decided), 3) + 4 * owns + 2 * rule + (team or area) + 2 * known_speaker


def ranked(batch: Batch, entities: Entities) -> tuple[list[Passage], list[Passage]]:
    """Pages and conversations worth extracting, each most promising first."""
    kinds = {d.id: d.kind for d in batch.docs}
    mentions = Mentions(entities)
    pages, talk = [], []
    for i, p in enumerate(batch.passages):
        kind = kinds.get(p.doc_id)
        if kind in PAGE_KINDS:
            s = mentions.score(p.text, kind)
            if s > 0:
                pages.append((-s, i, p))
        elif kind in CONVERSATIONS:
            s = conversation_score(mentions, p, entities.people)
            if s > 0:
                talk.append((-s, i, p))
    pages.sort(key=lambda row: row[:2])
    talk.sort(key=lambda row: row[:2])
    return [p for *_, p in pages], [p for *_, p in talk]


def select_passages(batch: Batch, entities: Entities, *, limit: int | None = None) -> list[Passage]:
    """The passages worth extracting, most promising first: pages (ownership statements, then process and policy),
    then conversations with a signal."""
    pages, talk = ranked(batch, entities)
    chosen = pages + talk
    return chosen[:limit] if limit is not None else chosen


def choose(
    batch: Batch, entities: Entities, *, limit: int | None = None, conversations: int | None = None
) -> tuple[list[Passage], list[Passage]]:
    """This run's passages and the ones left for a later run. At most `conversations` come from tickets and chats;
    they are kept out of `limit`'s reach, so pages never use up the conversations' share and the other way round."""
    pages, talk = ranked(batch, entities)
    talk_now = talk if conversations is None else talk[:conversations]
    room = None if limit is None else max(0, limit - len(talk_now))
    pages_now = pages if room is None else pages[:room]
    return pages_now + talk_now, pages[len(pages_now) :] + talk[len(talk_now) :]


# ----- the model -------------------------------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string", "enum": list(PREDICATES)},
                    "value": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["subject", "predicate", "value", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}


def system_prompt(entities: Entities) -> str:
    predicates = "\n".join(f"- {name}: {meaning}" for name, meaning in PREDICATES.items())
    areas = "\n".join(f"- area:{k} ({v})" for k, v in sorted(entities.areas.items()))
    teams = "\n".join(f"- team:{k} ({v})" for k, v in sorted(entities.teams.items()))
    people = "\n".join(f"- person:{k} ({v})" for k, v in sorted(entities.people.items()))
    return f"""You extract facts about how a company works from one passage of what it has written down: a page of its
documentation, or a turn in one of its conversations (an issue, a comment thread, a discussion, a forum or chat thread).

Return only facts the passage states directly about the company: who owns which product area, who is on or leads
which team, what was decided, how something is done, the rules people follow, which tools a team uses, and who to
contact about something. Skip opinions, advice to customers, examples, hypotheticals and general product
descriptions. Most passages hold zero to three facts; return an empty list when there are none.

A conversation turn starts with who said it and when. From a conversation, return only what the speaker states as
settled for the company or its team: a decision made, a change made ("we moved X to Y", "X is deprecated"), who owns
something, or how something is done. Skip questions, bug reports, requests, guesses, plans still under discussion,
and anything about one customer's own setup.

Each fact is a subject, a predicate, a value and a one-sentence text that restates the fact in plain words, as the
passage says it.

Predicates (use only these):
{predicates}

Keys:
- An area, team or person is written as its key from the lists below. Match names loosely: "the Feature Flags team" is
  team:feature-flags, and a product named in other words is the area whose name it matches. Never make up an area, team or person key.
- owned_by needs an area from the list as its subject and a team as its value. When a passage says a team owns
  something that is not in the areas list, use contact_for with a topic subject instead.
- Anything else is a topic: topic:<kebab-case slug> of one to four content words naming the thing itself, for
  example topic:friday-deploys, topic:support-hero-rotation, topic:expense-policy.
- A value that is not a key is a short phrase of at most twenty words.
- When a passage says one team owns several areas, return one owned_by fact per area.

Areas:
{areas}

Teams:
{teams}

People:
{people}"""


def _cache_key(text: str, model: str) -> str:
    """Per model, so facts a cheap development model extracted never stand in for the production model's."""
    return hashlib.sha1(f"{model}\n{text}".encode()).hexdigest()


async def _call(client, model: str, system: str, user: str, effort: str, usage: Usage) -> list[dict] | None:
    """One model call with retries on rate limits and overload. None when it kept failing."""
    for attempt in range(7):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            retry_after = getattr(getattr(e, "response", None), "headers", {}).get("retry-after") if status else None
            wait = float(retry_after) if retry_after else min(60.0, 2**attempt) + random.random()
            await asyncio.sleep(wait)
            continue
        except anthropic.APIStatusError as e:
            if e.status_code == 529:
                await asyncio.sleep(min(60.0, 2**attempt) + random.random())
                continue
            # Not worth retrying, and the next call would fail the same way (a spend limit, a bad key): stop
            # calling, and keep what is extracted or cached so far.
            usage.failed += 1
            usage.stopped = usage.stopped or f"{e.status_code}: {getattr(e, 'message', e)}"
            return None
        u = response.usage
        usage.calls += 1
        usage.input_tokens += u.input_tokens or 0
        usage.output_tokens += u.output_tokens or 0
        usage.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
        usage.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        if response.stop_reason in ("refusal", "max_tokens"):
            return []
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text).get("facts", [])
        except json.JSONDecodeError:
            return []
    usage.failed += 1
    return None


# ----- validation ------------------------------------------------------------------------------------------------


def _key(raw: str, allowed: tuple[str, ...], entities: Entities) -> str | None:
    """A model-given key or phrase, normalised, or None when it is not one this slot allows."""
    raw = raw.strip()
    prefix, sep, rest = raw.partition(":")
    prefix = prefix.lower().strip()
    if sep and prefix in ("area", "team", "person", "topic"):
        if prefix not in allowed:
            return None
        if prefix == "topic":
            return normalise_topic(rest)
        key = rest.strip().lower() if prefix == "person" else re.sub(r"[^a-z0-9]+", "-", rest.lower()).strip("-")
        return f"{prefix}:{key}" if entities.known(prefix, key) else None
    if "phrase" in allowed and raw:
        return raw[:MAX_PHRASE]
    return None


def validate(raw_facts: list[dict], entities: Entities, dropped: dict[str, int] | None = None) -> list[dict]:
    """Keep only facts in the vocabulary with known keys. Returns `{subject, predicate, value, text}` dicts."""
    kept = []
    for f in raw_facts:
        predicate = (f.get("predicate") or "").strip()
        reason = None
        if predicate not in PREDICATES:
            reason = "predicate"
        else:
            subjects, values = SHAPES[predicate]
            subject = _key(f.get("subject") or "", subjects, entities)
            value = _key(f.get("value") or "", values, entities)
            text = (f.get("text") or "").strip()
            if not subject:
                reason = "subject"
            elif not value:
                reason = "value"
            elif not text:
                reason = "text"
        if reason:
            if dropped is not None:
                dropped[reason] = dropped.get(reason, 0) + 1
            continue
        kept.append({"subject": subject, "predicate": predicate, "value": value, "text": text})
    return kept


def _fact_id(subject: str, predicate: str, value: str, passage_id: str) -> str:
    return hashlib.sha1(f"{subject}|{predicate}|{value}|{passage_id}".encode()).hexdigest()[:16]


KIND_WORDS = {
    "adr": "decision record",
    "pull": "pull request",
    "comment_thread": "comment thread",
    "discussion": "discussion",
    "forum": "forum thread",
    "slack_thread": "Slack thread",
    "wiki": "wiki page",
    "notion_page": "Notion page",
    "confluence_page": "Confluence page",
}


def to_facts(rows: list[tuple[Passage, Doc, dict]]) -> list[Fact]:
    """Validated rows to Facts: topics merged across pages, dated by the document, ranked by its kind."""
    topics = [k for _, _, r in rows for k in (r["subject"], r["value"]) if k.startswith("topic:")]
    merged = merge_topics(topics)
    facts: dict[str, Fact] = {}
    for passage, doc, r in rows:
        subject = merged.get(r["subject"], r["subject"])
        value = merged.get(r["value"], r["value"])
        fid = _fact_id(subject, r["predicate"], value, passage.id)
        facts[fid] = Fact(
            id=fid,
            subject=subject,
            predicate=r["predicate"],
            value=value,
            text=r["text"],
            valid_from=passage.at or (doc.decided_at if doc.kind in ("rfc", "adr") and doc.decided_at else doc.updated_at),
            passage_id=passage.id,
            authority=AUTHORITY[doc.kind],
        )
    return list(facts.values())


async def extract(
    passages: list[Passage],
    docs: Mapping[str, Doc] | Iterable[Doc],
    entities: Entities,
    *,
    model: str,
    concurrency: int = 8,
    cache_dir: Path | None = None,
    client=None,
    effort: str = "low",
    usage: Usage | None = None,
    on_passage: Callable[[], None] | None = None,
) -> list[Fact]:
    """Extract facts from passages. Model answers are cached per passage text under `cache_dir`. `on_passage` is
    called as each passage finishes, for progress."""
    docs = docs if isinstance(docs, Mapping) else {d.id: d for d in docs}
    usage = usage if usage is not None else Usage()
    system = system_prompt(entities)
    semaphore = asyncio.Semaphore(concurrency)
    if cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    async def one(passage: Passage) -> list[tuple[Passage, Doc, dict]]:
        doc = docs.get(passage.doc_id)
        if doc is None or doc.kind not in AUTHORITY:
            return []
        file = Path(cache_dir) / f"{_cache_key(passage.text, model)}.json" if cache_dir else None
        if file and file.exists():
            raw = json.loads(file.read_text())["facts"]
            usage.cached += 1
        else:
            api = client or _client()
            kind = KIND_WORDS.get(doc.kind, doc.kind.replace("_", " "))
            user = f"Document: {doc.title}\nKind: {kind}\n\nPassage:\n{passage.text}"
            async with semaphore:
                if usage.stopped:
                    usage.skipped += 1
                    return []
                raw = await _call(api, model, system, user, effort, usage)
            if raw is None:
                return []
            if file:
                file.write_text(json.dumps({"model": model, "facts": raw}, ensure_ascii=False))
        kept = validate(raw, entities, usage.dropped)
        usage.passages_with_facts += bool(kept)
        return [(passage, doc, r) for r in kept]

    async def counted(passage: Passage) -> list[tuple[Passage, Doc, dict]]:
        try:
            return await one(passage)
        finally:
            if on_passage:
                on_passage()

    results = await asyncio.gather(*(counted(p) for p in passages))
    return to_facts([row for rows in results for row in rows])


_shared_client = None


def _client():
    global _shared_client
    if _shared_client is None:
        _shared_client = anthropic.AsyncAnthropic(max_retries=0)
    return _shared_client
