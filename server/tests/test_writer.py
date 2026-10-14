from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch, write_facts
from canon.types import Activity, Area, Batch, Doc, Fact, Passage, Person, Team


def _batch() -> Batch:
    doc = Doc("handbook:notebooks.md", "handbook", "Notebooks", "https://posthog.com/handbook/notebooks", "2026-10-01", "timgl")
    passage = Passage("handbook:notebooks.md#0", doc.id, "Notebooks are owned by the Data tools team.")
    fact = Fact(
        id="f1",
        subject="area:notebooks",
        predicate="owned_by",
        value="team:data-tools",
        text="Notebooks are owned by the Data tools team.",
        valid_from="2026-10-01",
        passage_id=passage.id,
        authority=1,
    )
    return Batch(
        docs=[doc],
        passages=[passage],
        facts=[fact],
        people=[Person("timgl", "Tim", "Engineer")],
        teams=[Team("data-tools", "Data tools", members=("timgl",), leads=("timgl",))],
        areas=[Area("notebooks", "Notebooks")],
        activity=[Activity("timgl", doc.id, "AUTHORED", "2026-10-01")],
    )


def test_write_batch_creates_lineage(graph):
    ensure_schema(graph)
    write_batch(graph, _batch())
    rows = graph.query(
        "MATCH (f:Fact {id:'f1'})-[:STATED_IN]->(p:Passage)<-[:HAS]-(d:Document) RETURN f.text, p.text, d.url"
    ).result_set
    assert rows == [["Notebooks are owned by the Data tools team."] * 2 + ["https://posthog.com/handbook/notebooks"]]


def test_reingest_is_idempotent(graph):
    ensure_schema(graph)
    write_batch(graph, _batch())
    first = graph.query("MATCH (n) RETURN count(n)").result_set[0][0]
    edges = graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    write_batch(graph, _batch())
    assert graph.query("MATCH (n) RETURN count(n)").result_set[0][0] == first
    assert graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0] == edges


def test_fact_links_entities(graph):
    ensure_schema(graph)
    write_batch(graph, _batch())
    rows = graph.query("MATCH (a:Area)<-[:ABOUT]-(f:Fact)-[:VALUE]->(t:Team) RETURN a.slug, t.slug").result_set
    assert rows == [["notebooks", "data-tools"]]


def test_people_and_teams(graph):
    ensure_schema(graph)
    write_batch(graph, _batch())
    assert graph.query("MATCH (:Person {handle:'timgl'})-[:MEMBER_OF]->(t:Team) RETURN t.slug").result_set == [["data-tools"]]
    assert graph.query("MATCH (:Person {handle:'timgl'})-[:LEADS]->(t:Team) RETURN t.slug").result_set == [["data-tools"]]
    assert graph.query("MATCH (:Person {handle:'timgl'})-[:AUTHORED]->(d:Document) RETURN d.id").result_set == [["handbook:notebooks.md"]]


def test_topic_entity_created(graph):
    ensure_schema(graph)
    fact = Fact("f2", "topic:friday-deploys", "policy", "no deploys after 3pm", "No deploys after 3pm on Fridays.", "2026-05-01", "p", 1)
    write_facts(graph, [fact])
    assert graph.query("MATCH (t:Topic)<-[:ABOUT]-(:Fact {id:'f2'}) RETURN t.key").result_set == [["friday-deploys"]]
