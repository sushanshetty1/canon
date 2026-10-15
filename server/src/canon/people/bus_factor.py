"""The bus factor of each area: how many people hold its knowledge independently, and what it hinges on.

Counting the people who know an area overstates it when they know it through the same work: three reviewers of
one pull request are one piece of evidence, not three. So each area gets a three-layer flow network:

    (:Area) -[:FLOW {cap: 1}]-> (:Document) -[:FLOW {cap: WIDE}]-> (:Person) -[:FLOW {cap: 1}]-> (:Sink)

- The people are those who know the area well enough to answer for it: a KNOWS score of at least `MIN_SCORE` and
  at least `SHARE` of the area's top score.
- The documents are the area's evidence that one of them wrote, reviewed or decided (a comment is not enough).
  Each carries one unit: one document can back one person, however many people touched it.
- A document reaches everyone who wrote, reviewed or decided it. That edge is wide, so a cut never runs through it:
  a cut names documents or people, nothing in between.
- Each person passes on one unit: a person counts once, however much they did.

`algo.maxFlow` from the area to the sink is then the largest set of people who each hold the area through
evidence of their own (a maximum matching of people to documents). That is the bus factor. The minimum cut, read
from the residual network the flow leaves, names what the area hinges on: the people, or the documents, whose loss
would take that number down. Of the minimum cuts, the one nearest the sink is used, so a person is named wherever a
person, not a document, is the bottleneck.

A worked example. Replay has two pull requests. Alice wrote #1 and #2; Bob and Carol only reviewed #1.

    Replay -1-> #1 -> Alice, Bob, Carol        Alice -1-> sink
    Replay -1-> #2 -> Alice                    Bob   -1-> sink
                                               Carol -1-> sink

Three people know Replay, but the flow is 2: #2 can only back Alice, and #1 backs one of Bob and Carol. In the
residual network Bob and Carol can both still reach the sink, and #1 through them, while Alice's edge to the sink
and the edge into #1 are full. So the cut is {#1, Alice}: Replay hinges on Alice and on that one pull request,
since Bob and Carol know it only through #1. Had Bob written a pull request of his own, the flow would be 3.

Each area's network is built, run and removed in turn, since documents and people are shared between areas.
What stays on the graph:

- `a.bus_factor`, `a.knowers` (people above the bar) and `a.evidence_docs` (documents in the network);
- `(:Area)-[:FLOWS_TO {docs, via}]->(:Person)` for each person in the network: how many of its documents they hold,
  and the document the flow routed to them (null when they were not needed);
- `(:Area)-[:DEPENDS_ON]->(:Person)` and `(:Area)-[:HINGES_ON]->(:Document)`: the minimum cut.

The exact Cypher is in `docs/bus-factor.md`.
"""

import json
from collections import deque
from dataclasses import dataclass

MIN_SCORE = 3.0  # about one pull request authored this half year
SHARE = 0.25  # of the area's top KNOWS score
SINK = "knowledge"
WIDE = 1_000_000  # a document reaches all its people; its own edge from the area is the limit
FLOW_TIMEOUT_MS = 120_000


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


def sink_side_cut(edges: list[FlowEdge], flows: dict[int, float], sink: int) -> tuple[set[int], list[FlowEdge]]:
    """The minimum cut closest to the sink: everything that can still reach the sink in the residual network is on
    its side. Of all minimum cuts this one sits furthest downstream, so it names people wherever a person, rather
    than a document, is what the flow hinges on."""
    eps = 1e-9
    into: dict[int, list[int]] = {}
    for e in edges:
        f = flows.get(e.id, 0.0)
        if e.cap - f > eps:
            into.setdefault(e.dst, []).append(e.src)
        if f > eps:
            into.setdefault(e.src, []).append(e.dst)
    side = {sink}
    queue = deque([sink])
    while queue:
        for prev in into.get(queue.popleft(), ()):
            if prev not in side:
                side.add(prev)
                queue.append(prev)
    return side, [e for e in edges if e.src not in side and e.dst in side]


MAX_FLOW = """
MATCH (s) WHERE id(s) = $source
MATCH (t:Sink {id: $sink})
CALL algo.maxFlow({sourceNodes: [s], targetNodes: [t], capacityProperty: 'cap', relationshipTypes: ['FLOW']})
YIELD edges, edgeFlows, maxFlow
RETURN [e IN edges | id(e)], edgeFlows, maxFlow
"""


def max_flow(graph, source: int, sink: str = SINK) -> tuple[float, dict[int, float]]:
    """`algo.maxFlow` from a node to the sink: the flow's value, and the flow on each edge that carries some."""
    # The flow over a busy area's thousands of documents takes a few seconds, past the server's default limit.
    rows = graph.query(MAX_FLOW, {"source": source, "sink": sink}, timeout=FLOW_TIMEOUT_MS).result_set
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

# One area's network. The evidence: documents about the area (linked to it, or stating facts about it) that one of
# its knowers wrote, reviewed or decided.
EVIDENCE = """
MATCH (a:Area {slug: $area})
MATCH (p:Person)-[:AUTHORED|REVIEWED|DECIDED]->(d:Document)
WHERE p.handle IN $knowers
  AND ((d)-[:ABOUT]->(a)
       OR (d.kind <> 'ownership_map' AND (d)-[:HAS]->(:Passage)<-[:STATED_IN]-(:Fact)-[:ABOUT]->(a)))
WITH a, d, collect(DISTINCT p) AS people
CREATE (a)-[:FLOW {cap: 1}]->(d)
WITH d, people
UNWIND people AS p
CREATE (d)-[:FLOW {cap: $wide}]->(p)
"""

TO_SINK = """
MATCH (:Area {slug: $area})-[:FLOW]->(:Document)-[:FLOW]->(p:Person)
WITH DISTINCT p
MATCH (t:Sink {id: $sink})
CREATE (p)-[:FLOW {cap: 1}]->(t)
"""

CLEAR = "MATCH ()-[e:FLOW]->() DELETE e"


@dataclass
class AreaFlow:
    area: str
    bus: int = 0
    knowers: int = 0
    docs: int = 0
    people: dict[str, dict] | None = None  # handle -> {"docs": n, "via": doc id or None}
    cut_people: list[str] | None = None
    cut_docs: list[str] | None = None


def area_flow(graph, area: str, knowers: list[str]) -> AreaFlow:
    """Build one area's network, run the flow, read the cut, and remove the network."""
    graph.query(CLEAR)
    result = AreaFlow(area, knowers=len(knowers), people={}, cut_people=[], cut_docs=[])
    if not knowers:
        return result
    graph.query(EVIDENCE, {"area": area, "knowers": knowers, "wide": WIDE})
    graph.query(TO_SINK, {"area": area, "sink": SINK})
    try:
        source = graph.query("MATCH (a:Area {slug: $area}) RETURN id(a)", {"area": area}).result_set[0][0]
        edges = flow_edges(graph)
        if not edges:
            return result
        prefix = {"Person": "p:", "Document": "d:", "Sink": "s:"}
        names = {
            i: prefix.get(label, "") + str(key)
            for i, label, key in graph.query(
                "MATCH (n)-[:FLOW]-() WITH DISTINCT n RETURN id(n), labels(n)[0], coalesce(n.handle, n.id)"
            ).result_set
        }
        sink = next(i for i, n in names.items() if n.startswith("s:"))
        value, flows = max_flow(graph, source)
        _, cut = sink_side_cut(edges, flows, sink)
        docs_of: dict[str, int] = {}
        via: dict[str, str] = {}
        for e in edges:
            src, dst = names.get(e.src, ""), names.get(e.dst, "")
            if src.startswith("d:") and dst.startswith("p:"):
                docs_of[dst[2:]] = docs_of.get(dst[2:], 0) + 1
                if flows.get(e.id, 0) > 0.5:
                    via[dst[2:]] = src[2:]
        result.bus = int(round(value))
        result.docs = sum(1 for e in edges if e.src == source)
        result.people = {h: {"docs": n, "via": via.get(h)} for h, n in docs_of.items()}
        for e in cut:
            src, dst = names.get(e.src, ""), names.get(e.dst, "")
            if dst.startswith("d:"):
                result.cut_docs.append(dst[2:])
            elif src.startswith("p:"):
                result.cut_people.append(src[2:])
        result.cut_docs.sort()
        result.cut_people.sort()
        return result
    finally:
        graph.query(CLEAR)


def compute(graph) -> dict[str, int]:
    """Run the flow for every area and store each area's bus factor, its network's shape and its minimum cut."""
    graph.query("MERGE (:Sink {id: $sink})", {"sink": SINK})
    knowers = dict(graph.query(KNOWERS, {"min_score": MIN_SCORE, "share": SHARE}).result_set)
    areas = [r[0] for r in graph.query("MATCH (a:Area) RETURN a.slug ORDER BY a.slug").result_set]
    results = [area_flow(graph, slug, sorted(knowers.get(slug, []))) for slug in areas]

    for rel in ("DEPENDS_ON", "HINGES_ON", "FLOWS_TO"):
        graph.query(f"MATCH (:Area)-[r:{rel}]->() DELETE r")
    graph.query(
        """UNWIND $rows AS r MATCH (a:Area {slug: r.area})
           SET a.bus_factor = r.bus, a.knowers = r.knowers, a.evidence_docs = r.docs""",
        {"rows": [{"area": r.area, "bus": r.bus, "knowers": r.knowers, "docs": r.docs} for r in results]},
    )
    flows = [{"area": r.area, "handle": h, **v} for r in results for h, v in (r.people or {}).items()]
    deps = [{"area": r.area, "handle": h} for r in results for h in r.cut_people or []]
    hinges = [{"area": r.area, "doc": d} for r in results for d in r.cut_docs or []]
    if flows:
        graph.query(
            """UNWIND $rows AS r MATCH (a:Area {slug: r.area}), (p:Person {handle: r.handle})
               CREATE (a)-[:FLOWS_TO {docs: r.docs, via: r.via}]->(p)""",
            {"rows": flows},
        )
    if deps:
        graph.query(
            """UNWIND $rows AS r MATCH (a:Area {slug: r.area}), (p:Person {handle: r.handle})
               CREATE (a)-[:DEPENDS_ON]->(p)""",
            {"rows": deps},
        )
    if hinges:
        graph.query(
            """UNWIND $rows AS r MATCH (a:Area {slug: r.area}), (d:Document {id: r.doc})
               CREATE (a)-[:HINGES_ON]->(d)""",
            {"rows": hinges},
        )
    return {
        "areas": len(results),
        "with_knowers": sum(1 for r in results if r.bus),
        "bus_factor_1": sum(1 for r in results if r.bus == 1),
        "below_head_count": sum(1 for r in results if r.bus and r.bus < len(r.people or {})),
        "depends_on": len(deps),
        "hinges_on": len(hinges),
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

NETWORK = """
MATCH (a:Area)-[f:FLOWS_TO]->(p:Person)
OPTIONAL MATCH (v:Document {id: f.via})
OPTIONAL MATCH (a)-[d:DEPENDS_ON]->(p)
RETURN a.slug, p.handle, coalesce(p.name, p.handle), f.docs, v.id, v.title, v.url, v.kind, d IS NOT NULL
ORDER BY f.docs DESC, p.handle
"""

HINGES = """
MATCH (a:Area)-[:HINGES_ON]->(d:Document)
OPTIONAL MATCH (p:Person)-[:AUTHORED|REVIEWED|DECIDED]->(d) WHERE (a)-[:FLOWS_TO]->(p)
RETURN a.slug, d.id, coalesce(d.title, d.id), coalesce(d.url, ''), coalesce(d.kind, ''), collect(DISTINCT p.handle)
ORDER BY d.id
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


def _doc(id, title, url, kind) -> dict | None:
    return {"id": id, "title": title, "url": url, "kind": kind} if id else None


def org_view(graph, *, top: int = 6) -> list[dict]:
    """Every area with its owner teams, bus factor, its flow network and its minimum cut, riskiest first.

    Riskiest is the smallest bus factor above zero, and among equals the area with the most evidence, since a busy
    area resting on one person is the bigger risk. Areas nobody shows up for in the record come last.
    """
    own = owners(graph)
    people = {slug: rows for slug, rows in graph.query(PEOPLE).result_set}
    network: dict[str, list[dict]] = {}
    for slug, handle, name, docs, vid, vtitle, vurl, vkind, dep in graph.query(NETWORK).result_set:
        network.setdefault(slug, []).append(
            {"handle": handle, "name": name, "docs": docs, "via": _doc(vid, vtitle, vurl, vkind), "cut": dep}
        )
    hinges: dict[str, list[dict]] = {}
    for slug, did, title, url, kind, handles in graph.query(HINGES).result_set:
        hinges.setdefault(slug, []).append({**_doc(did, title, url, kind), "people": sorted(handles)})
    areas = graph.query(
        """MATCH (a:Area) RETURN a.slug, coalesce(a.name, a.slug), coalesce(a.bus_factor, 0), coalesce(a.knowers, 0),
                  coalesce(a.evidence_docs, 0)"""
    ).result_set
    out = []
    for slug, name, bus, knowers, docs in areas:
        rows = people.get(slug, [])
        weight = sum(r["score"] for r in rows)
        out.append(
            {
                "slug": slug,
                "name": name,
                "owners": own.get(slug, []),
                "bus_factor": bus,
                "knowers": knowers,
                "evidence_docs": docs,
                "evidence": round(weight, 2),
                "network": network.get(slug, []),
                "depends_on": [_person(r) for r in rows if r["depends"]],
                "hinges_on": hinges.get(slug, []),
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
