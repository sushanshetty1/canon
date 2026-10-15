from canon.graph.db import ensure_schema
from canon.graph.privacy import handles_only
from canon.graph.writer import write_batch
from canon.types import Batch, Doc, Fact, Passage, Person


def test_canon_text_uses_handles_and_quotes_stay(graph):
    ensure_schema(graph)
    doc = Doc("handbook:x", "handbook", "X", "https://x", "2026-01-01")
    passage = Passage("handbook:x#0", doc.id, "Paul D'Ambra leads Replay.")
    fact = Fact("f1", "person:pauldambra", "leads", "team:replay", "Paul D'Ambra leads the Replay team.", "2026-01-01", passage.id, 1)
    write_batch(
        graph,
        Batch(docs=[doc], passages=[passage], facts=[fact], people=[Person("pauldambra", "Paul D'Ambra"), Person("name:jane-doe", "Jane Doe")]),
    )
    assert handles_only(graph)["facts"] == 1
    assert graph.query("MATCH (f:Fact {id:'f1'}) RETURN f.text").result_set == [["pauldambra leads the Replay team."]]
    assert graph.query("MATCH (p:Passage) RETURN p.text").result_set == [["Paul D'Ambra leads Replay."]]
    names = dict(graph.query("MATCH (p:Person) RETURN p.handle, p.name").result_set)
    assert names == {"pauldambra": "pauldambra", "name:jane-doe": "Jane Doe"}
    assert handles_only(graph)["facts"] == 0
