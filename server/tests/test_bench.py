from canon.bench.grade import mentions
from canon.bench.questions import build
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.types import Area, Batch, Doc, Fact, Passage, Person, Team


def _graph(graph):
    ensure_schema(graph)
    docs = [Doc(f"ownership_map:{i}", "ownership_map", "Ownership map", f"https://x/{i}", d) for i, d in ((1, "2025-01-01"), (2, "2026-06-01"))]
    passages = [Passage(f"{d.id}#0", d.id, "map") for d in docs]
    facts = [
        Fact("a1", "area:notebooks", "owned_by", "team:old", "Old owns notebooks.", "2025-01-01", passages[0].id, 3, valid_to="2026-06-01"),
        Fact("a2", "area:notebooks", "owned_by", "team:new", "New owns notebooks.", "2026-06-01", passages[1].id, 3),
        Fact("b1", "area:alerts", "owned_by", "team:old", "Old owns alerts.", "2025-01-01", passages[0].id, 3),
    ]
    write_batch(
        graph,
        Batch(
            docs=docs,
            passages=passages,
            facts=facts,
            areas=[Area("notebooks", "Notebooks"), Area("alerts", "Alerts")],
            teams=[Team("old", "Old", leads=("octo",)), Team("new", "New", leads=("name:someone",))],
            people=[Person("octo", "Octo"), Person("name:someone", "Someone")],
        ),
    )


def test_questions_come_from_dated_ownership(graph):
    _graph(graph)
    qs = {q["question"]: q for q in build(graph)}
    moved = qs["Which team owns Notebooks?"]
    assert moved["category"] == "changed" and moved["gold"] == ["New"] and moved["stale"] == ["Old"]
    assert qs["Which team owns Alerts?"]["category"] == "control"
    assert qs["Which team owned Notebooks before New?"]["gold"] == ["Old"]


def test_lead_questions_name_people_by_handle_only(graph):
    _graph(graph)
    leads = [q for q in build(graph) if q["category"] == "lead"]
    assert [q["gold"] for q in leads] == [["octo"]]


def test_mentions_matches_whole_names_loosely():
    assert mentions("The Context & MCP team owns it.", ["Context & MCP"])
    assert not mentions("The Context team owns it.", ["Context & MCP"])
