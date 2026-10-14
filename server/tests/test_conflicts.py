import asyncio

from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.verify.conflicts import judge
from canon.verify.supersede import link
from canon.types import Batch, Doc, Fact, Passage


class Stub:
    """Says the first two statements it sees conflict, and counts how often it was asked."""

    def __init__(self):
        self.calls = 0

    async def json(self, system, prompt, schema):
        self.calls += 1
        return {"conflicts": [{"a": 0, "b": 1, "why": "Fridays both allowed and frozen", "cannot_both_hold": True}]}


def _company(graph, extra_doc_fact: bool = True):
    docs = [
        Doc("handbook:a", "handbook", "Deploys", "https://x/a", "2026-09-01"),
        Doc("handbook:b", "handbook", "Freeze", "https://x/b", "2026-09-10"),
    ]
    passages = [Passage("handbook:a#0", "handbook:a", "Deploy any day."), Passage("handbook:b#0", "handbook:b", "No Friday deploys.")]
    facts = [
        Fact("f1", "topic:friday-deploys", "policy", "allowed", "Deploys are allowed on Fridays.", "2026-09-01", "handbook:a#0", 1),
        Fact("f2", "topic:friday-deploys", "policy", "frozen", "No deploys on Fridays.", "2026-09-10", "handbook:b#0", 1),
    ]
    ensure_schema(graph)
    write_batch(graph, Batch(docs=docs, passages=passages, facts=facts))


def test_policy_sentences_are_not_disputed_by_link(graph):
    _company(graph)
    assert link(graph)["contradicts"] == 0


def test_judged_conflict_is_kept_by_link_and_not_rejudged(graph):
    _company(graph)
    link(graph)
    stub = Stub()
    assert asyncio.run(judge(graph, stub))["conflicts"] == 1
    link(graph)
    rows = graph.query("MATCH (a:Fact)-[e:CONTRADICTS]->(b:Fact) RETURN a.id, b.id, e.reason").result_set
    assert rows == [["f1", "f2", "judged"]]
    asyncio.run(judge(graph, stub))
    assert stub.calls == 1


def test_one_document_is_never_judged_against_itself(graph):
    ensure_schema(graph)
    doc = Doc("handbook:a", "handbook", "Deploys", "https://x/a", "2026-09-01")
    p = [Passage("handbook:a#0", doc.id, "x"), Passage("handbook:a#1", doc.id, "y")]
    f = [
        Fact("f1", "topic:t", "process", "a", "A.", "2026-09-01", p[0].id, 1),
        Fact("f2", "topic:t", "process", "b", "B.", "2026-09-01", p[1].id, 1),
    ]
    write_batch(graph, Batch(docs=[doc], passages=p, facts=f))
    stub = Stub()
    assert asyncio.run(judge(graph, stub))["topics"] == 0
    assert stub.calls == 0
