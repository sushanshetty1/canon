"""Finds current process and policy statements that cannot both be true, and links them as disputed.

The graph picks the candidates: current facts about one topic, stated in different documents. Facts stated in one
document are never compared, because one page rarely contradicts itself and when it does it is one fix. A model
then reads each topic's statements and names the pairs that conflict (one says Fridays are fine, another says
Fridays are frozen), not the pairs that merely add detail. Each conflict becomes
`(a)-[:CONTRADICTS {reason: 'judged', why}]->(b)`, which `supersede.link` leaves in place.

A topic is judged once per set of current facts: its `judged` property holds a hash of the fact ids it was judged
on, so a second run only asks about topics whose facts changed.
"""

import asyncio
import hashlib
from itertools import combinations

from canon.llm import JsonModel

PREDICATES = ("process", "policy")
MAX_FACTS = 16  # a topic with more current statements than this is too broad to judge as one

CANDIDATES = """
MATCH (f:Fact)-[:STATED_IN]->(:Passage)<-[:HAS]-(d:Document)
WHERE f.predicate IN $predicates AND f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->()
RETURN f.subject, f.id, f.text, d.id, d.title, coalesce(d.updated_at, '')
"""
# No aggregation: FalkorDB 6.0.2 crashes when it groups on a key that can be null.

SYSTEM = """You compare statements a company's documents make about one topic. Each statement is current: no newer
source replaced it. Name only the pairs that cannot both be followed or true at the same time, such as "deploys are
allowed on Fridays" and "no deploys on Fridays". Statements that add detail, cover different cases, or say the same
thing in other words do not conflict, and neither do a general rule and its stated exception. Write `why` first;
set `cannot_both_hold` to true only if following one statement means breaking the other. Most topics have no
conflicts; return an empty list then."""

SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                    "why": {"type": "string"},
                    "cannot_both_hold": {"type": "boolean"},
                },
                "required": ["a", "b", "why", "cannot_both_hold"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conflicts"],
    "additionalProperties": False,
}


def _topics(rows: list[list]) -> dict[str, list[dict]]:
    topics: dict[str, dict[str, dict]] = {}
    for subject, fid, text, doc, title, updated in rows:
        topics.setdefault(subject, {})[fid] = {"id": fid, "text": text, "doc": doc, "title": title, "date": updated}
    # Only topics stated by more than one document can hold a dispute.
    return {
        s: sorted(fs.values(), key=lambda f: f["id"])
        for s, fs in topics.items()
        if 1 < len(fs) <= MAX_FACTS and len({f["doc"] for f in fs.values()}) > 1
    }


def _signature(facts: list[dict]) -> str:
    return hashlib.sha1("|".join(f["id"] for f in facts).encode()).hexdigest()[:16]


async def _judge_topic(subject: str, facts: list[dict], model: JsonModel) -> list[tuple[str, str, str]]:
    lines = "\n".join(f"{i}. {f['text']} ({f['title']}, {f['date'][:10]})" for i, f in enumerate(facts))
    out = await model.json(SYSTEM, f"Topic: {subject}\n\n{lines}", SCHEMA)
    allowed = {(i, j) for i, j in combinations(range(len(facts)), 2) if facts[i]["doc"] != facts[j]["doc"]}
    found = []
    for c in out.get("conflicts", []):
        i, j = sorted((c.get("a", -1), c.get("b", -1)))
        if (i, j) in allowed and c.get("cannot_both_hold") is True:
            found.append((facts[i]["id"], facts[j]["id"], c.get("why", "")))
    return found


async def judge(graph, model: JsonModel, *, concurrency: int = 8) -> dict[str, int]:
    topics = _topics(graph.query(CANDIDATES, {"predicates": list(PREDICATES)}).result_set)
    done = dict(graph.query("MATCH (t:Topic) WHERE t.judged IS NOT NULL RETURN t.key, t.judged").result_set)
    todo = {s: fs for s, fs in topics.items() if done.get(s.removeprefix("topic:")) != _signature(fs)}
    semaphore = asyncio.Semaphore(concurrency)

    async def one(subject: str, facts: list[dict]):
        async with semaphore:
            return subject, await _judge_topic(subject, facts, model)

    results = await asyncio.gather(*(one(s, fs) for s, fs in todo.items()), return_exceptions=True)
    conflicts, judged, failed = [], [], 0
    for result in results:
        if isinstance(result, BaseException):
            failed += 1
            continue
        subject, found = result
        conflicts += [{"a": a, "b": b, "why": why} for a, b, why in found]
        judged.append({"key": subject.removeprefix("topic:"), "sig": _signature(topics[subject])})

    # A re-judged topic's old verdicts are replaced by the new ones.
    graph.query(
        """UNWIND $keys AS k MATCH (:Topic {key: k})<-[:ABOUT]-(a:Fact)-[e:CONTRADICTS {reason: 'judged'}]->(:Fact)
           DELETE e""",
        {"keys": [j["key"] for j in judged]},
    )
    if conflicts:
        graph.query(
            """UNWIND $rows AS r MATCH (a:Fact {id: r.a}), (b:Fact {id: r.b})
               MERGE (a)-[e:CONTRADICTS]->(b) SET e.reason = 'judged', e.why = r.why""",
            {"rows": conflicts},
        )
    if judged:
        graph.query("UNWIND $rows AS r MATCH (t:Topic {key: r.key}) SET t.judged = r.sig", {"rows": judged})
    return {"topics": len(topics), "judged": len(judged), "conflicts": len(conflicts), "failed": failed}
