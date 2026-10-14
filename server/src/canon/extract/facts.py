"""Passages to facts, with the extract model.

The model reads one passage with its document title and the lists of known areas, teams and people, and returns
facts as `{subject, predicate, value, text}` through a structured output. Nothing it returns is trusted as is:

- the predicate must be in the closed vocabulary, and the subject and value must have the shape it allows;
- area, team and person keys must be ones the graph already knows; unknown keys drop the fact;
- topic keys are normalised and merged, so the same topic from different pages lands on one key.

Each fact starts to hold on its document's date (an RFC's on the day it was accepted) and carries its source's
authority. Extraction is the expensive step, so it runs only on passages likely to carry facts (handbook, team pages
and RFCs that name a team, an area, a person or a process), and every model answer is cached on disk by the
passage text: a second run over unchanged pages costs nothing.
"""

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from canon.extract.predicates import AUTHORITY, PREDICATES, SHAPES, merge_topics, normalise_topic
from canon.types import Batch, Doc, Fact, Passage

EXTRACT_KINDS = ("handbook", "team_page", "rfc")
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
            people={p.handle: p.name for p in batch.people if not p.handle.startswith("name:")},
        )

    def known(self, prefix: str, key: str) -> bool:
        table = {"area": self.areas, "team": self.teams, "person": self.people}.get(prefix)
        return table is not None and key in table


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

    def cost_usd(self, input_per_mtok: float = 2.0, output_per_mtok: float = 10.0) -> float:
        """At Sonnet 5.5 prices: cache reads 0.1x input, 5-minute cache writes 1.25x."""
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


def select_passages(batch: Batch, entities: Entities, *, limit: int | None = None) -> list[Passage]:
    """The passages worth extracting, most promising first: ownership statements, then process and policy."""
    kinds = {d.id: d.kind for d in batch.docs}
    mentions = Mentions(entities)
    scored = []
    for i, p in enumerate(batch.passages):
        kind = kinds.get(p.doc_id)
        if kind not in EXTRACT_KINDS:
            continue
        s = mentions.score(p.text, kind)
        if s > 0:
            scored.append((-s, i, p))
    scored.sort(key=lambda row: row[:2])
    chosen = [p for _, _, p in scored]
    return chosen[:limit] if limit is not None else chosen


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
    return f"""You extract facts about how a company works from one passage of its documentation.

Return only facts the passage states directly about the company: who owns which product area, who is on or leads
which team, what was decided, how something is done, the rules people follow, which tools a team uses, and who to
contact about something. Skip opinions, advice to customers, examples, hypotheticals and general product
descriptions. Most passages hold zero to three facts; return an empty list when there are none.

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


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


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
            valid_from=(doc.decided_at if doc.kind == "rfc" and doc.decided_at else doc.updated_at),
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
) -> list[Fact]:
    """Extract facts from passages. Model answers are cached per passage text under `cache_dir`."""
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
        file = Path(cache_dir) / f"{_cache_key(passage.text)}.json" if cache_dir else None
        if file and file.exists():
            raw = json.loads(file.read_text())["facts"]
            usage.cached += 1
        else:
            api = client or _client()
            user = f"Document: {doc.title}\nKind: {doc.kind.replace('_', ' ')}\n\nPassage:\n{passage.text}"
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

    results = await asyncio.gather(*(one(p) for p in passages))
    return to_facts([row for rows in results for row in rows])


_shared_client = None


def _client():
    global _shared_client
    if _shared_client is None:
        _shared_client = anthropic.AsyncAnthropic(max_retries=0)
    return _shared_client
