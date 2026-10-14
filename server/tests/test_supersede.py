from kit import Kit, edges, prop

from canon.graph.writer import write_batch
from canon.types import Batch, Doc, Passage
from canon.verify.supersede import link

OWNS = ("area:notebooks", "owned_by")


def test_newer_value_supersedes(graph):
    k = Kit(graph)
    k.fact("old", *OWNS, "team:product-analytics", kind="ownership_map", on="2026-02-01")
    k.fact("new", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01")
    k.fact("page", *OWNS, "team:product-analytics", kind="handbook", on="2026-03-01")
    k.write()
    counts = link(graph)
    assert ("SUPERSEDED_BY", "old", "new") in edges(graph)
    assert ("SUPERSEDED_BY", "page", "new") in edges(graph)  # older and lower authority: replaced, not stale
    assert prop(graph, "old", "valid_to") == "2026-09-01"
    assert prop(graph, "new", "valid_to") is None
    assert not prop(graph, "page", "stale")
    assert counts["superseded"] == 2 and counts["stale"] == 0 and counts["contradicts"] == 0


def test_same_value_restates_not_supersedes(graph):
    k = Kit(graph)
    k.fact("map", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01")
    k.fact("team", *OWNS, "team:data-tools", kind="team_page", on="2026-09-20")
    k.write()
    link(graph)
    assert edges(graph) == {("RESTATES", "team", "map")}
    assert prop(graph, "map", "valid_to") is None and prop(graph, "team", "valid_to") is None


def test_lower_authority_restatement_is_stale_not_disputed(graph):
    k = Kit(graph)
    k.fact("map-old", *OWNS, "team:product-analytics", kind="ownership_map", on="2026-02-01")
    k.fact("map", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01")
    k.fact("handbook", *OWNS, "team:product-analytics", kind="handbook", on="2026-10-01")
    k.write()
    counts = link(graph)
    found = edges(graph)
    assert ("SUPERSEDED_BY", "handbook", "map") in found
    assert not any(t == "CONTRADICTS" for t, *_ in found)
    assert prop(graph, "handbook", "stale") is True
    assert prop(graph, "map", "stale") is None and prop(graph, "map", "valid_to") is None
    assert counts["stale"] == 1 and counts["stale_pages"] == 1


def test_equal_authority_disagreement_contradicts(graph):
    k = Kit(graph)
    k.fact("a", "topic:friday-deploys", "decided", "no deploys after 2pm on fridays", on="2026-09-10")
    k.fact("b", "topic:friday-deploys", "decided", "deploys allowed any day with on-call approval", on="2026-09-24")
    k.write()
    counts = link(graph)
    assert edges(graph) == {("CONTRADICTS", "a", "b")}
    assert prop(graph, "a", "valid_to") is None and prop(graph, "b", "valid_to") is None
    assert counts["contradicts"] == 1


def test_equal_authority_far_apart_supersedes(graph):
    k = Kit(graph)
    k.fact("a", "topic:friday-deploys", "decided", "no deploys on fridays", on="2026-03-01")
    k.fact("b", "topic:friday-deploys", "decided", "deploys allowed any day", on="2026-09-24")
    k.write()
    link(graph)
    assert edges(graph) == {("SUPERSEDED_BY", "a", "b")}
    assert prop(graph, "a", "valid_to") == "2026-09-24"


def test_old_fact_on_recently_edited_page_still_disputes(graph):
    # The fact dates from March, but its page was edited a week before the other source: both are current.
    k = Kit(graph)
    k.fact("a", "topic:friday-deploys", "decided", "no deploys on fridays", on="2026-03-01", doc_updated="2026-09-17")
    k.fact("b", "topic:friday-deploys", "decided", "deploys allowed any day", on="2026-09-24")
    k.write()
    link(graph)
    assert edges(graph) == {("CONTRADICTS", "a", "b")}


def test_ended_fact_is_superseded_even_inside_the_window(graph):
    # The ownership map moved an area twice in a week; the connector closed the first window.
    k = Kit(graph)
    k.fact("m1", *OWNS, "team:a", kind="ownership_map", on="2026-09-01", valid_to="2026-09-05")
    k.fact("m2", *OWNS, "team:b", kind="ownership_map", on="2026-09-05")
    k.write()
    link(graph)
    assert edges(graph) == {("SUPERSEDED_BY", "m1", "m2")}
    assert prop(graph, "m1", "closed_by") is None  # the connector's window is left alone


def test_multi_valued_predicate_adds_not_replaces(graph):
    k = Kit(graph)
    k.fact("u1", "team:replay", "uses", "rrweb", on="2026-01-01")
    k.fact("u2", "team:replay", "uses", "clickhouse", on="2026-09-01")
    k.write()
    link(graph)
    assert edges(graph) == set()


def test_changed_page_closes_old_facts(graph):
    k = Kit(graph)
    k.fact("kept", *OWNS, "team:data-tools", doc="handbook:notebooks", on="2026-05-01")
    k.fact("gone", "topic:notebook-sharing", "process", "share by link", doc="handbook:notebooks", on="2026-05-01")
    k.write()
    link(graph)
    assert prop(graph, "gone", "valid_to") is None
    # The page changes: its second passage is gone.
    doc = Doc("handbook:notebooks", "handbook", "Notebooks", "https://example.com/n", "2026-10-01")
    write_batch(graph, Batch(docs=[doc], passages=[Passage("handbook:notebooks#0", doc.id, "Data tools owns notebooks.")]))
    counts = link(graph)
    removed_at = graph.query("MATCH (p:Passage {id: 'handbook:notebooks#1'}) RETURN p.removed_at").result_set[0][0]
    assert removed_at and prop(graph, "gone", "valid_to") == removed_at
    assert prop(graph, "gone", "closed_by") == "removed"
    assert prop(graph, "kept", "valid_to") is None
    assert counts["closed_removed"] == 1
    # The fact is closed, not deleted: it still shows where it came from.
    assert graph.query("MATCH (:Fact {id:'gone'})-[:STATED_IN]->(:Passage)<-[:HAD]-(d:Document) RETURN d.id").result_set


def _snapshot(graph):
    props = graph.query("MATCH (f:Fact) RETURN f.id, f.valid_to, f.closed_by, f.stale ORDER BY f.id").result_set
    return edges(graph), props


def test_link_is_idempotent(graph):
    k = Kit(graph)
    k.fact("map-old", *OWNS, "team:product-analytics", kind="ownership_map", on="2026-02-01")
    k.fact("map", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01")
    k.fact("handbook", *OWNS, "team:product-analytics", on="2026-10-01")
    k.fact("team", *OWNS, "team:data-tools", kind="team_page", on="2026-09-10")
    k.fact("a", "topic:friday-deploys", "decided", "no deploys after 2pm", on="2026-09-10")
    k.fact("b", "topic:friday-deploys", "decided", "deploy any day", on="2026-09-24")
    k.write()
    first = link(graph)
    before = _snapshot(graph)
    assert link(graph) == first
    assert _snapshot(graph) == before
    # Re-ingesting the same facts resets what the writer owns; linking again restores the same state.
    k.write()
    assert link(graph) == first
    assert _snapshot(graph) == before


def _map(owners: dict[str, list[str]]) -> str:
    entries = "".join(f"    {s}: {{\n        feature: '{s.upper()}',\n        owner: {t!r},\n    }},\n" for s, t in owners.items())
    return f"const FEATURE_DATA: Record<string, BaseFeature> = {{\n{entries}}}\n"


def test_co_owners_from_the_ownership_map_both_hold(graph):
    from canon.sources.posthog import ownership_history

    versions = [
        {"sha": "a" * 40, "date": "2026-06-05", "text": _map({"cli": ["error-tracking"]})},
        {"sha": "b" * 40, "date": "2026-09-18", "text": _map({"cli": ["error-tracking", "context-and-mcp"]})},
    ]
    own = ownership_history(versions, lambda slug: slug)
    k = Kit(graph)
    k.batch.docs += own.docs
    k.batch.passages += own.passages
    k.batch.facts += own.facts
    k.fact("page", "area:cli", "owned_by", "team:error-tracking", kind="handbook", on="2026-10-01")
    k.write()
    counts = link(graph)
    current = graph.query(
        "MATCH (f:Fact {predicate: 'owned_by', authority: 3}) WHERE f.valid_to IS NULL "
        "AND NOT (f)-[:SUPERSEDED_BY]->() RETURN f.value ORDER BY f.value"
    ).result_set
    assert current == [["team:context-and-mcp"], ["team:error-tracking"]]
    # Naming one of two owners is neither out of date nor a dispute.
    assert counts["contradicts"] == 0 and counts["stale"] == 0
