"""The bus factor of each area: how many people could still answer for it, and who they are.

For every area the graph holds a flow network `(:Area)-[:FLOW {cap: 1}]->(:Person)-[:FLOW {cap: 1}]->(:Sink)` over
the people who know the area well enough: a KNOWS score of at least `MIN_SCORE` and at least `SHARE` of the area's
top score, so a passing comment does not count as knowing it. `algo.maxFlow` from the area to the sink gives the
bus factor. The people the area depends on are those on a minimum cut: the flow's saturated edges that separate
what the source can still reach in the residual network from what it cannot. `min_cut` recovers that cut from the
flow alone, for any network.

The result is stored on the graph: `a.bus_factor`, `a.knowers` and `(:Area)-[:DEPENDS_ON]->(:Person)`, replaced on
every run. `org_view` reads them back, riskiest area first.
"""

import json
from collections import deque
from dataclasses import dataclass

MIN_SCORE = 3.0  # about one pull request authored this half year
SHARE = 0.25  # of the area's top KNOWS score
SINK = "knowledge"


@dataclass(frozen=True)
class FlowEdge:
    id: int
    src: int
    dst: int
    cap: float


def min_cut(edges: list[FlowEdge], flows: dict[int, float], source: int) -> tuple[set[int], list[FlowEdge]]:
    """The source side of a minimum cut and the edges that cross it, given a maximum flow.

    In the residual network an edge keeps `cap - flow` forward and `flow` backward. Everything the source still
    reaches is its side of the cut; every edge from that side to the other is saturated, and together they are a
    minimum cut (max-flow min-cut theorem).
    """
    eps = 1e-9
    out: dict[int, list[int]] = {}
    for e in edges:
        f = flows.get(e.id, 0.0)
        if e.cap - f > eps:
            out.setdefault(e.src, []).append(e.dst)
        if f > eps:
            out.setdefault(e.dst, []).append(e.src)
    seen = {source}
    queue = deque([source])
    while queue:
        for nxt in out.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen, [e for e in edges if e.src in seen and e.dst not in seen]


MAX_FLOW = """
MATCH (s) WHERE id(s) = $source
MATCH (t:Sink {id: $sink})
CALL algo.maxFlow({sourceNodes: [s], targetNodes: [t], capacityProperty: 'cap', relationshipTypes: ['FLOW']})
YIELD edges, edgeFlows, maxFlow
RETURN [e IN edges | id(e)], edgeFlows, maxFlow
"""


def max_flow(graph, source: int, sink: str = SINK) -> tuple[float, dict[int, float]]:
    """`algo.maxFlow` from a node to the sink: the flow's value, and the flow on each edge that carries some."""
    rows = graph.query(MAX_FLOW, {"source": source, "sink": sink}).result_set
    if not rows:
        return 0.0, {}
    ids, flows, value = rows[0]
    return float(value or 0), {i: float(f) for i, f in zip(ids or [], flows or [])}


def flow_edges(graph) -> list[FlowEdge]:
    rows = graph.query("MATCH (a)-[e:FLOW]->(b) RETURN id(e), id(a), id(b), e.cap").result_set
    return [FlowEdge(i, a, b, float(c)) for i, a, b, c in rows]


# Who knows each area well enough to answer for it.
KNOWERS = """
MATCH (p:Person)-[k:KNOWS]->(a:Area)
WITH a, max(k.score) AS top
MATCH (p:Person)-[k:KNOWS]->(a)
WHERE k.score >= $min_score AND k.score >= $share * top
RETURN a.slug, collect(p.handle)
"""


def build_network(graph) -> dict[str, list[str]]:
    """Replace the flow network with one built from the current KNOWS edges. Returns each area's knowers."""
    graph.query("MATCH (:Area)-[e:FLOW]->(:Person) DELETE e")
    graph.query("MATCH (:Person)-[e:FLOW]->(:Sink) DELETE e")
    graph.query("MERGE (:Sink {id: $sink})", {"sink": SINK})
    knowers = dict(graph.query(KNOWERS, {"min_score": MIN_SCORE, "share": SHARE}).result_set)
    rows = [{"area": a, "handle": h} for a, hs in knowers.items() for h in hs]
    if rows:
        graph.query(
            """UNWIND $rows AS r MATCH (a:Area {slug: r.area}), (p:Person {handle: r.handle})
               CREATE (a)-[:FLOW {cap: 1}]->(p)""",
            {"rows": rows},
        )
        graph.query(
            """UNWIND $handles AS h MATCH (p:Person {handle: h}), (t:Sink {id: $sink})
               CREATE (p)-[:FLOW {cap: 1}]->(t)""",
            {"handles": sorted({r["handle"] for r in rows}), "sink": SINK},
        )
    return knowers


def compute(graph) -> dict[str, int]:
    """Build the network, run the flow for every area, and store each area's bus factor and the people on its cut."""
    knowers = build_network(graph)
    nodes = dict(graph.query("MATCH (a:Area) RETURN a.slug, id(a)").result_set)
    handles = dict(graph.query("MATCH (p:Person)-[:FLOW]->(:Sink) RETURN id(p), p.handle").result_set)
    edges = flow_edges(graph)
    results = []
    for slug, node in nodes.items():
        if not knowers.get(slug):
            results.append({"area": slug, "bus": 0, "knowers": 0, "cut": []})
            continue
        value, flows = max_flow(graph, node)
        _, cut = min_cut(edges, flows, node)
        people = sorted({handles[n] for e in cut for n in (e.src, e.dst) if n in handles})
        results.append({"area": slug, "bus": int(round(value)), "knowers": len(knowers[slug]), "cut": people})

    graph.query("MATCH (:Area)-[d:DEPENDS_ON]->(:Person) DELETE d")
    graph.query(
        "UNWIND $rows AS r MATCH (a:Area {slug: r.area}) SET a.bus_factor = r.bus, a.knowers = r.knowers",
        {"rows": results},
    )
    deps = [{"area": r["area"], "handle": h} for r in results for h in r["cut"]]
    if deps:
        graph.query(
            """UNWIND $rows AS r MATCH (a:Area {slug: r.area}), (p:Person {handle: r.handle})
               CREATE (a)-[:DEPENDS_ON]->(p)""",
            {"rows": deps},
        )
    return {
        "areas": len(results),
        "with_knowers": sum(1 for r in results if r["bus"]),
        "bus_factor_1": sum(1 for r in results if r["bus"] == 1),
        "depends_on": len(deps),
    }


# ----- reading it back -------------------------------------------------------------------------------------------

OWNERS = """
MATCH (f:Fact {predicate: 'owned_by'})-[:ABOUT]->(a:Area), (f)-[:VALUE]->(t:Team)
WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->() AND f.authority >= 3
RETURN a.slug, collect(DISTINCT {slug: t.slug, name: coalesce(t.name, t.slug)})
"""

PEOPLE = """
MATCH (p:Person)-[k:KNOWS]->(a:Area)
OPTIONAL MATCH (a)-[d:DEPENDS_ON]->(p)
WITH a, p, k, d ORDER BY k.score DESC, p.handle
RETURN a.slug, collect({handle: p.handle, name: coalesce(p.name, p.handle), score: k.score,
                        evidence: k.evidence, depends: d IS NOT NULL})
"""


def evidence(raw: str | None) -> dict:
    base = {"decided": 0, "authored": 0, "reviewed": 0, "commented": 0, "member": False}
    if raw:
        try:
            base.update(json.loads(raw))
        except ValueError:
            pass
    return base


def owners(graph) -> dict[str, list[dict]]:
    return {slug: sorted(teams, key=lambda t: t["slug"]) for slug, teams in graph.query(OWNERS).result_set}


def org_view(graph, *, top: int = 6) -> list[dict]:
    """Every area with its owner teams, bus factor and the people it depends on, riskiest first.

    Riskiest is the smallest bus factor above zero, and among equals the area with the most evidence, since a busy
    area resting on one person is the bigger risk. Areas nobody shows up for in the record come last.
    """
    own = owners(graph)
    people = {slug: rows for slug, rows in graph.query(PEOPLE).result_set}
    areas = graph.query(
        "MATCH (a:Area) RETURN a.slug, coalesce(a.name, a.slug), coalesce(a.bus_factor, 0), coalesce(a.knowers, 0)"
    ).result_set
    out = []
    for slug, name, bus, knowers in areas:
        rows = people.get(slug, [])
        weight = sum(r["score"] for r in rows)
        out.append(
            {
                "slug": slug,
                "name": name,
                "owners": own.get(slug, []),
                "bus_factor": bus,
                "knowers": knowers,
                "evidence": round(weight, 2),
                "depends_on": [_person(r) for r in rows if r["depends"]],
                "people": [_person(r) for r in rows[:top]],
                "others": max(0, len(rows) - top),
            }
        )
    out.sort(key=lambda a: (a["bus_factor"] == 0, a["bus_factor"], -a["evidence"], a["slug"]))
    return out


def _person(row: dict) -> dict:
    return {
        "handle": row["handle"],
        "name": row["name"],
        "score": round(row["score"], 2),
        "evidence": evidence(row["evidence"]),
        "depends": row["depends"],
    }
