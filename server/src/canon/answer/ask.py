"""Ask: retrieve, draft, check, as a stream of events.

Events, in order:

- `{"type": "evidence", "facts": n, "documents": n}`
- `{"type": "claim", "index": i, "text": ..., "fact_ids": [...]}`, every claim as soon as the draft returns
- `{"type": "verdict", "index": i, "verdict": ..., "sources": [...], "newer": [...], "conflicting": [...]}`, each
  as its check finishes, so they can arrive out of order
- `{"type": "done", "counts": {"verified": n, "stale": n, "disputed": n, "unsupported": n}}`

or, after `evidence`, `{"type": "empty", "ask": [{"handle", "name", "why"}], "passages": [...]}` when nothing found
answers the question. Then no answer is drafted; the people to ask come from ownership in the graph, and the
closest passages are offered as places to look, never as claims.

Questions about the workspace itself ("what sources are connected") are answered from the graph's structure by
`canon.answer.inventory`, with the same events.
"""

import asyncio
from collections.abc import AsyncIterator

from canon.answer import inventory
from canon.answer.draft import draft
from canon.answer.retrieve import retrieve
from canon.llm import JsonModel, answer_model, check_model
from canon.verify.check import Checked, Claim, Entail, check, make_entail

VERDICTS = ("verified", "stale", "disputed", "unsupported")

OWNERS = """
MATCH (f:Fact {predicate: 'owned_by'})-[:ABOUT]->(a:Area {slug: $slug})
WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->()
RETURN f.value, coalesce(a.name, a.slug) ORDER BY f.authority DESC
"""
LEADS = "MATCH (p:Person)-[:LEADS]->(t:Team {slug: $slug}) RETURN p.handle, coalesce(p.name, p.handle), coalesce(t.name, t.slug)"
# coalesce keeps the grouping keys non-null: FalkorDB 6.0.2 crashes when it groups on a null.
MEMBERS = """
MATCH (p:Person)-[:MEMBER_OF]->(t:Team {slug: $slug})
OPTIONAL MATCH (p)-[a:AUTHORED|REVIEWED|COMMENTED|DECIDED]->(:Document)
RETURN p.handle, coalesce(p.name, p.handle), coalesce(t.name, t.slug), count(a) AS n ORDER BY n DESC, p.handle LIMIT 3
"""


CLOSEST = """
CALL db.idx.fulltext.queryNodes('Passage', $q) YIELD node, score
MATCH (d:Document)-[:HAS]->(node)
RETURN coalesce(d.title, d.id), d.url, coalesce(d.kind, ''), coalesce(d.updated_at, ''), node.text
ORDER BY score DESC LIMIT 3
"""


def closest_passages(graph, question: str) -> list[dict]:
    """When no fact answers, the passages that come closest: places to look, not claims."""
    from canon.answer.retrieve import search_terms

    terms = search_terms(question)
    if not terms:
        return []
    rows = graph.query(CLOSEST, {"q": "|".join(terms)}).result_set
    return [{"title": t, "url": u, "kind": k, "date": d[:10] or None, "text": (x or "")[:400]} for t, u, k, d, x in rows]


def _team_people(graph, slug: str, why_lead: str, why_member: str) -> list[dict]:
    leads = graph.query(LEADS, {"slug": slug}).result_set
    if leads:
        return [{"handle": h, "name": n, "why": why_lead.format(team=t)} for h, n, t in leads]
    rows = graph.query(MEMBERS, {"slug": slug}).result_set
    return [{"handle": h, "name": n, "why": why_member.format(team=t)} for h, n, t, _ in rows]


def who_to_ask(graph, entities: list[str], *, limit: int = 3) -> list[dict]:
    """The lead of the team that owns a named area; otherwise the most active members of a named team."""
    people: list[dict] = []
    for key in entities:
        prefix, _, slug = key.partition(":")
        if prefix == "area":
            for value, area in graph.query(OWNERS, {"slug": slug}).result_set:
                if str(value).startswith("team:"):
                    people += _team_people(graph, value[5:], f"Leads {{team}}, which owns {area}.", f"On {{team}}, which owns {area}.")
                elif str(value).startswith("person:"):  # a CODEOWNERS owner can be one person
                    rows = graph.query("MATCH (p:Person {handle: $h}) RETURN coalesce(p.name, p.handle)", {"h": value[7:]}).result_set
                    people.append({"handle": value[7:], "name": rows[0][0] if rows else value[7:], "why": f"Owns {area}."})
    if not people:
        for key in entities:
            if key.startswith("team:"):
                people += _team_people(graph, key[5:], "Leads {team}.", "On {team}.")
    unique: dict[str, dict] = {}
    for p in people:
        unique.setdefault(p["handle"], p)
    return list(unique.values())[:limit]


async def _checked(index: int, graph, claim: Claim, entail: Entail) -> tuple[int, Checked, bool]:
    try:
        return index, await check(graph, claim, entail=entail), True
    except Exception:
        return index, Checked(claim, "unsupported"), False


async def ask(
    graph, question: str, *, model: JsonModel | None = None, entail: Entail | None = None, limit: int = 24
) -> AsyncIterator[dict]:
    if inventory.is_inventory(question):  # about the workspace itself: answered from the graph's structure
        async for event in inventory.events(graph):
            yield event
        return
    evidence = await asyncio.to_thread(retrieve, graph, question, limit=limit)
    yield {"type": "evidence", "facts": len(evidence.facts), "documents": evidence.documents}

    claims = await draft(question, evidence, model=model or answer_model()) if evidence.facts else []
    if not claims and inventory.maybe_inventory(question):
        async for event in inventory.events(graph, evidence=False):
            yield event
        return
    if not claims:
        yield {
            "type": "empty",
            "ask": await asyncio.to_thread(who_to_ask, graph, evidence.entities),
            "passages": await asyncio.to_thread(closest_passages, graph, question),
        }
        return
    for i, claim in enumerate(claims):
        yield {"type": "claim", "index": i, "text": claim.text, "fact_ids": claim.fact_ids}

    entail = entail or make_entail(check_model())
    tasks = [asyncio.create_task(_checked(i, graph, c, entail)) for i, c in enumerate(claims)]
    counts = dict.fromkeys(VERDICTS, 0)
    try:
        for next_done in asyncio.as_completed(tasks):
            index, checked, ok = await next_done
            counts[checked.verdict] += 1
            event = checked.event(index)
            if not ok:
                event["error"] = "The check could not run for this sentence."
            yield event
    finally:
        for t in tasks:
            t.cancel()
    yield {"type": "done", "counts": counts}
