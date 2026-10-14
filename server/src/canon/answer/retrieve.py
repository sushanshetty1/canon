"""Question to evidence: the facts an answer may use, each labelled current or replaced.

1. Full-text search over passages finds the facts stated in the best passages.
2. Areas, teams, people and topics named in the question bring the facts about them.
3. Every fact found is followed along `SUPERSEDED_BY` to the fact that holds now, and to any current fact that
   contradicts it, so the drafter sees what changed and where sources disagree.
"""

import re
from dataclasses import dataclass, field

from canon.graph import read

STOPWORDS = frozenset(
    """a about after all also am an and any are as at be been before being but by can could did do does doing
    for from had has have how i if in into is it its me my no not now of on or our should so some than that the
    their them then there these they this those to was we were what when where which while who whom whose why
    will with would you your currently today still ever""".split()
)
FULLTEXT = """
CALL db.idx.fulltext.queryNodes('Passage', $q) YIELD node, score
MATCH (f:Fact)-[:STATED_IN]->(node)
RETURN f.id, score ORDER BY score DESC LIMIT 60
"""
# Most passages (issues, pull requests, forum threads) carry no facts, so the limit applies after the match:
# limiting passages first lets them crowd out the handbook passages facts come from.
ENTITY_LABELS = {"Area": ("area", "slug"), "Team": ("team", "slug"), "Person": ("person", "handle"), "Topic": ("topic", "key")}


@dataclass
class Evidence:
    facts: list[dict] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    @property
    def documents(self) -> int:
        return len({f["source"]["doc_id"] for f in self.facts if f["source"]["doc_id"]})


SUFFIXES = ("ations", "ation", "ating", "ates", "ated", "ate", "ions", "ion", "ing", "ers", "er", "ed", "es", "s")


def stem(word: str) -> str:
    """A light stemmer, enough that "escalate", "escalated" and "escalation" meet."""
    if len(word) <= 4 or word.endswith("ss"):
        return word
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())]


def search_terms(question: str) -> list[str]:
    """Content words only, so nothing reaches the full-text query that its syntax would read as an operator."""
    return list(dict.fromkeys(w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in STOPWORDS and len(w) > 1))


def _span(hay: list[str], needle: list[str]) -> tuple[int, int] | None:
    n = len(needle)
    for i in range(len(hay) - n + 1):
        if hay[i : i + n] == needle:
            return i, i + n
    return None


def match_entities(graph, question: str) -> list[str]:
    """Entity keys whose name, slug or handle appears in the question. A match inside a longer one is dropped:
    "session replay" names the area, not also the team called Replay."""
    words = tokens(question)
    found: dict[str, tuple[int, int]] = {}
    for label, (prefix, prop) in ENTITY_LABELS.items():
        rows = graph.query(f"MATCH (e:{label}) RETURN e.{prop}, e.name").result_set
        for key, name in rows:
            if not key:
                continue
            for phrase in {name or "", str(key).removeprefix("name:").replace("-", " ")}:
                needle = tokens(phrase)
                if not needle or all(w in STOPWORDS for w in needle) or len("".join(needle)) < 3:
                    continue
                span, k = _span(words, needle), f"{prefix}:{key}"
                if not span and label == "Topic" and len(needle) > 1 and set(needle) <= set(words):
                    # A topic key is a bag of words: "ticket-escalation" matches "escalate a support ticket".
                    span = (min(words.index(w) for w in needle), max(words.index(w) for w in needle) + 1)
                if span and (k not in found or span[1] - span[0] > found[k][1] - found[k][0]):
                    found[k] = span
    inside = lambda a, b: b[0] <= a[0] and a[1] <= b[1] and a != b  # noqa: E731
    return [k for k, s in found.items() if not any(inside(s, o) for o in found.values())]


def _entity_facts(graph, keys: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    by_label: dict[str, list[str]] = {}
    for key in keys:
        prefix, _, rest = key.partition(":")
        label = next(lb for lb, (p, _) in ENTITY_LABELS.items() if p == prefix)
        by_label.setdefault(label, []).append(rest)
    for label, values in by_label.items():
        prop = ENTITY_LABELS[label][1]
        for rel, weight in (("ABOUT", 3.0), ("VALUE", 1.5)):
            rows = graph.query(
                f"""MATCH (f:Fact)-[:{rel}]->(e:{label}) WHERE e.{prop} IN $values
                    RETURN f.id ORDER BY f.authority DESC, f.valid_from DESC LIMIT 200""",
                {"values": values},
            ).result_set
            for (fid,) in rows:
                scores[fid] = max(scores.get(fid, 0.0), weight)
    return scores


def _shape(f: dict, replaced_by: str | None = None, disputed_with: list[str] | None = None) -> dict:
    return {
        "id": f["fact_id"],
        "text": f["fact"],
        "subject": f["subject"],
        "predicate": f["predicate"],
        "value": f["value"],
        "current": f["current"],
        "stale": f["stale"],
        "valid_from": f["valid_from"],
        "valid_to": f["valid_to"],
        "authority": f["authority"],
        "replaced_by": replaced_by,
        "disputed_with": disputed_with or [],
        "source": {k: f[k] for k in ("doc_id", "title", "url", "kind", "date", "passage")},
    }


def retrieve(graph, question: str, *, limit: int = 24) -> Evidence:
    entities = match_entities(graph, question)
    scores = _entity_facts(graph, entities)
    terms = search_terms(question)
    if terms:
        hits = graph.query(FULLTEXT, {"q": "|".join(terms)}).result_set
        top = max((s for _, s in hits), default=1.0) or 1.0
        for fid, score in hits:
            scores[fid] = scores.get(fid, 0.0) + 2.0 * score / top
    if not scores:
        return Evidence(entities=entities)

    found = read.facts(graph, scores)
    rank = lambda f: (scores[f["fact_id"]] + (1.0 if f["current"] else 0.0) + 0.25 * (f["authority"] or 0), f["valid_from"] or "")  # noqa: E731
    chosen = sorted(found.values(), key=rank, reverse=True)[:limit]
    ids = [f["fact_id"] for f in chosen]

    ends = read.chain_ends(graph, [f["fact_id"] for f in chosen if not f["current"]])
    partners = read.conflicts(graph, [f["fact_id"] for f in chosen if f["current"]])
    added = list(dict.fromkeys([*ends.values(), *(c for cs in partners.values() for c in cs)]))
    found.update(read.facts(graph, [i for i in added if i not in found]))
    ids += [i for i in added if i not in ids]
    facts = [_shape(found[i], ends.get(i), partners.get(i)) for i in ids if i in found]
    return Evidence(facts=facts, entities=entities)
