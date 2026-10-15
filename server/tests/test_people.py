"""Who knows each area, and its bus factor, on small graphs built by hand."""

import json

import pytest
from fastapi.testclient import TestClient

from canon.api.app import create_app
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.people import bus_factor, expertise
from canon.people.bus_factor import FlowEdge, max_flow, min_cut
from canon.people.views import area_people, person
from canon.types import Activity, Area, Batch, Doc, Fact, Passage, Person, Team

TODAY = "2026-10-15"
HALF_YEAR_AGO = "2026-04-18"  # 180 days before TODAY


def _doc(id, kind="pull", areas=("replay",), on=TODAY):
    return Doc(id, kind, f"Doc {id}", f"https://example.com/{id}", on, areas=areas)


def world(graph) -> None:
    """Replay is owned by the replay team (alice, bob); flags by the flags team (carol)."""
    ensure_schema(graph)
    om = Doc("ownership_map:abc", "ownership_map", "Ownership map", "https://example.com/om", "2026-01-01")
    passages = [Passage("ownership_map:abc#0", om.id, "Replay is owned by replay. Flags by flags.")]
    facts = [
        Fact("o1", "area:replay", "owned_by", "team:replay", "Replay is owned by the Replay team.", "2026-01-01",
             passages[0].id, 3),
        Fact("o2", "area:flags", "owned_by", "team:flags", "Flags are owned by the Flags team.", "2026-01-01",
             passages[0].id, 3),
    ]
    batch = Batch(
        docs=[_doc("pull:1"), _doc("pull:2"), _doc("rfc:r1", kind="rfc"), _doc("pull:9", areas=("flags",)), om],
        passages=passages,
        facts=facts,
        people=[Person(h, h.title()) for h in ("alice", "bob", "carol", "dave", "erin", "zed")],
        teams=[Team("replay", "Replay", ("alice", "bob"), ("alice",)), Team("flags", "Flags", ("carol",))],
        areas=[Area("replay", "Replay"), Area("flags", "Feature flags")],
        activity=[
            Activity("alice", "pull:1", "AUTHORED", TODAY),
            Activity("alice", "pull:2", "AUTHORED", TODAY),
            Activity("bob", "pull:1", "REVIEWED", TODAY),
            Activity("dave", "pull:2", "COMMENTED", TODAY),
            Activity("erin", "rfc:r1", "DECIDED", HALF_YEAR_AGO),
            # Editing the ownership map is bookkeeping: it says nothing about knowing replay.
            Activity("zed", "ownership_map:abc", "AUTHORED", TODAY),
        ],
    )
    write_batch(graph, batch)


def knows(graph) -> dict[tuple[str, str], dict]:
    rows = graph.query(
        "MATCH (p:Person)-[k:KNOWS]->(a:Area) RETURN p.handle, a.slug, k.score, k.evidence, k.docs"
    ).result_set
    return {(h, a): {"score": round(s, 3), "evidence": json.loads(e), "docs": d} for h, a, s, e, d in rows}


# ----- expertise -------------------------------------------------------------------------------------------------


def test_scores_weigh_each_kind_of_evidence_and_membership(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    k = knows(graph)
    assert k[("alice", "replay")]["score"] == 3 + 3 + 2  # two pull requests authored, and the owning team
    assert k[("bob", "replay")]["score"] == 2 + 2  # one review, and the owning team
    assert k[("dave", "replay")]["score"] == 1  # one comment
    assert k[("carol", "flags")]["score"] == 2  # membership alone
    assert ("zed", "replay") not in k


def test_recency_halves_the_weight_every_180_days(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    assert knows(graph)[("erin", "replay")]["score"] == pytest.approx(4 / 2, abs=0.01)


def test_evidence_holds_counts_and_the_top_documents(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    alice = knows(graph)[("alice", "replay")]
    assert alice["evidence"] == {"decided": 0, "authored": 2, "reviewed": 0, "commented": 0, "member": True}
    assert sorted(alice["docs"]) == ["pull:1", "pull:2"]
    assert knows(graph)[("carol", "flags")]["docs"] == []


def test_recomputing_is_idempotent_and_drops_what_no_longer_holds(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    first = knows(graph)
    expertise.compute(graph, today=TODAY)
    assert knows(graph) == first
    graph.query("MATCH (:Person {handle: 'dave'})-[r:COMMENTED]->() DELETE r")
    result = expertise.compute(graph, today=TODAY)
    assert ("dave", "replay") not in knows(graph) and result["removed"] == 1
    assert graph.query("MATCH ()-[k:KNOWS]->() RETURN count(k)").result_set[0][0] == len(first) - 1


def test_documents_linked_through_facts_count(graph):
    world(graph)
    page = Doc("handbook:replay.md", "handbook", "Replay", "https://example.com/replay", TODAY)
    p = Passage("handbook:replay.md#0", page.id, "Replay keeps recordings for 30 days.")
    f = Fact("h1", "area:replay", "retention", "30 days", p.text, TODAY, p.id, 1)
    write_batch(graph, Batch(docs=[page], passages=[p], facts=[f], activity=[Activity("dave", page.id, "AUTHORED", TODAY)]))
    expertise.compute(graph, today=TODAY)
    assert knows(graph)[("dave", "replay")]["score"] == 1 + 3


# ----- the flow and its cut --------------------------------------------------------------------------------------


def test_min_cut_from_a_flow_alone():
    # s -> a -> t and s -> b -> a: everything funnels through a -> t.
    edges = [FlowEdge(1, 0, 10, 1), FlowEdge(2, 0, 11, 1), FlowEdge(3, 11, 10, 1), FlowEdge(4, 10, 99, 1)]
    side, cut = min_cut(edges, {1: 1.0, 4: 1.0}, source=0)
    assert side == {0, 10, 11}
    assert [e.id for e in cut] == [4]


def _network(graph, spec: str):
    """Build FLOW edges from `a>b:cap` pairs; `t` is the sink. Returns node ids by name."""
    ensure_schema(graph)
    names = sorted({n for pair in spec.split() for n in pair.split(":")[0].split(">")})
    for n in names:
        if n == "t":
            graph.query("CREATE (:Sink {id: 'knowledge'})")
        else:
            graph.query("CREATE (:Person {handle: $h})", {"h": n})
    for pair in spec.split():
        ends, cap = pair.split(":")
        a, b = ends.split(">")
        match_b = "(y:Sink {id: 'knowledge'})" if b == "t" else "(y:Person {handle: $b})"
        graph.query(f"MATCH (x:Person {{handle: $a}}), {match_b} CREATE (x)-[:FLOW {{cap: $cap}}]->(y)",
                    {"a": a, "b": b, "cap": int(cap)})
    ids = dict(graph.query("MATCH (p:Person) RETURN p.handle, id(p)").result_set)
    ids["t"] = graph.query("MATCH (s:Sink) RETURN id(s)").result_set[0][0]
    return ids


def test_maxflow_cut_on_a_bottleneck(graph):
    # Two people know the area, but both learned it from h: h alone carries everything.
    ids = _network(graph, "s>p1:1 s>p2:1 p1>h:1 p2>h:1 h>t:1")
    value, flows = max_flow(graph, ids["s"])
    side, cut = min_cut(bus_factor.flow_edges(graph), flows, ids["s"])
    assert value == 1
    assert [(e.src, e.dst) for e in cut] == [(ids["h"], ids["t"])]


def test_maxflow_cut_through_a_shared_teacher(graph):
    # a and b both learned from m1; c learned from m2. Three people know it, but only two paths exist, and the
    # cut closest to the source runs through c's own link and through m1.
    ids = _network(graph, "s>a:1 s>b:1 s>c:1 a>m1:1 b>m1:1 c>m2:1 m1>t:1 m2>t:1")
    value, flows = max_flow(graph, ids["s"])
    side, cut = min_cut(bus_factor.flow_edges(graph), flows, ids["s"])
    names = {v: k for k, v in ids.items()}
    assert value == 2
    assert {names[n] for n in side} == {"s", "a", "b", "m1"}
    assert sorted((names[e.src], names[e.dst]) for e in cut) == [("m1", "t"), ("s", "c")]


def test_bus_factor_counts_who_could_still_answer(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    result = bus_factor.compute(graph)
    rows = dict(graph.query("MATCH (a:Area) RETURN a.slug, a.bus_factor").result_set)
    # alice 8 and bob 4 know replay; dave (1) and erin (2) are below the bar. Carol's membership alone is not enough.
    assert rows == {"replay": 2, "flags": 0}
    deps = graph.query("MATCH (:Area {slug: 'replay'})-[:DEPENDS_ON]->(p) RETURN p.handle ORDER BY p.handle").result_set
    assert deps == [["alice"], ["bob"]]
    assert result["with_knowers"] == 1
    # Running again replaces the network and the cut rather than adding to them.
    bus_factor.compute(graph)
    assert graph.query("MATCH ()-[d:DEPENDS_ON]->() RETURN count(d)").result_set[0][0] == 2
    assert graph.query("MATCH ()-[f:FLOW]->() RETURN count(f)").result_set[0][0] == 4


def test_one_person_holding_an_area_is_a_bus_factor_of_one(graph):
    world(graph)
    graph.query("MATCH (:Person {handle: 'bob'})-[r:REVIEWED]->() DELETE r")
    graph.query("MATCH (:Person {handle: 'bob'})-[r:MEMBER_OF]->() DELETE r")
    expertise.compute(graph, today=TODAY)
    bus_factor.compute(graph)
    view = bus_factor.org_view(graph)
    assert [a["slug"] for a in view] == ["replay", "flags"]  # riskiest first; no evidence last
    replay = view[0]
    assert replay["bus_factor"] == 1 and [p["handle"] for p in replay["depends_on"]] == ["alice"]
    assert replay["owners"] == [{"slug": "replay", "name": "Replay"}]
    assert replay["people"][0]["evidence"]["authored"] == 2


# ----- views and the API -----------------------------------------------------------------------------------------


def test_area_people_carries_the_documents_behind_each_person(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    bus_factor.compute(graph)
    found = area_people(graph, "replay")
    assert found["area"]["bus_factor"] == 2 and found["total"] == 4
    alice = found["people"][0]
    assert alice["handle"] == "alice" and alice["depends"] and alice["teams"] == ["Replay"]
    assert {d["id"] for d in alice["docs"]} == {"pull:1", "pull:2"}
    assert alice["docs"][0]["acts"] == [{"rel": "authored", "at": TODAY}]
    assert area_people(graph, "nowhere") is None


def test_person_lists_the_areas_they_know(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    bus_factor.compute(graph)
    found = person(graph, "Alice")
    assert found["person"]["teams"] == ["Replay"]
    assert [(a["slug"], a["depends"]) for a in found["areas"]] == [("replay", True)]
    assert person(graph, "nobody") is None


def test_people_routes(graph):
    world(graph)
    expertise.compute(graph, today=TODAY)
    bus_factor.compute(graph)
    client = TestClient(create_app(graph_for=lambda ws: graph if ws == "demo" else None))
    areas = client.get("/api/w/demo/areas").json()
    assert areas["computed"] and areas["areas"][0]["slug"] == "replay"
    assert client.get("/api/w/demo/areas/replay/people").json()["people"][0]["handle"] == "alice"
    assert client.get("/api/w/demo/areas/nope/people").status_code == 404
    assert client.get("/api/w/demo/people/bob").json()["areas"][0]["slug"] == "replay"
    assert client.get("/api/w/demo/people/nobody").status_code == 404
    assert client.get("/api/w/elsewhere/areas").status_code == 404
