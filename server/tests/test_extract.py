"""Fact extraction: the vocabulary, key validation, topic merging and caching, with a stub model client."""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from canon.extract.facts import Entities, Usage, extract, select_passages, validate
from canon.extract.predicates import AUTHORITY, PREDICATES, merge_topics, normalise_topic
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch, write_facts
from canon.sources.posthog import load_posthog
from canon.types import Doc, Passage

from test_posthog import fixture_fetch

ENTITIES = Entities(
    areas={"notebooks": "Notebooks", "actions": "Actions"},
    teams={"data-tools": "Data Tools", "billing": "Billing", "product-analytics": "Product Analytics"},
    people={"annaszell": "Anna Szell"},
)


class StubClient:
    """Answers every call with the same facts, and counts the calls."""

    def __init__(self, facts: list[dict]):
        self.calls = 0
        self.facts = facts
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kwargs):
        self.calls += 1
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        assert "thinking" not in kwargs
        usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        text = SimpleNamespace(type="text", text=json.dumps({"facts": self.facts}))
        return SimpleNamespace(content=[text], usage=usage, stop_reason="end_turn")


def test_vocabulary_and_authority():
    assert set(PREDICATES) == {"owned_by", "member_of", "leads", "decided", "process", "policy", "uses", "contact_for"}
    assert AUTHORITY["ownership_map"] > AUTHORITY["team_page"] > AUTHORITY["handbook"] > AUTHORITY["forum"]


def test_normalise_topic_slug():
    assert normalise_topic("topic:The Friday deploys") == "topic:friday-deploys"
    assert normalise_topic("How we do on-call for the support hero rotation") == "topic:do-call-support-hero"
    assert normalise_topic("topic:the of and") is None
    merged = merge_topics(["topic:friday-deploys", "topic:deploys-friday", "topic:deploy-friday", "topic:deploys"])
    assert merged["topic:friday-deploys"] == merged["topic:deploys-friday"] == merged["topic:deploy-friday"]
    assert merged["topic:deploys"] == "topic:deploys"  # broader, so kept apart


def test_rejects_unknown_entity_keys():
    dropped: dict[str, int] = {}
    kept = validate(
        [
            {"subject": "area:notebooks", "predicate": "owned_by", "value": "team:data-tools", "text": "Notebooks are owned by Data Tools."},
            {"subject": "area:notebooks", "predicate": "owned_by", "value": "team:imaginary", "text": "x"},
            {"subject": "area:made-up", "predicate": "owned_by", "value": "team:billing", "text": "x"},
            {"subject": "topic:revenue-queries", "predicate": "owned_by", "value": "team:billing", "text": "x"},
            {"subject": "area:notebooks", "predicate": "likes", "value": "team:billing", "text": "x"},
            {"subject": "topic:The Revenue Queries", "predicate": "contact_for", "value": "team:Billing", "text": "Ask Billing."},
            {"subject": "person:AnnaSzell", "predicate": "member_of", "value": "team:data-tools", "text": "Anna is in Data Tools."},
        ],
        ENTITIES,
        dropped,
    )
    assert [(f["subject"], f["predicate"], f["value"]) for f in kept] == [
        ("area:notebooks", "owned_by", "team:data-tools"),
        ("topic:revenue-queries", "contact_for", "team:billing"),
        ("person:annaszell", "member_of", "team:data-tools"),
    ]
    assert dropped == {"value": 1, "subject": 2, "predicate": 1}


def test_extract_dates_and_caches(tmp_path):
    doc = Doc("rfc:x.md", "rfc", "RFC: X", "https://example.com/x", "2026-09-01", decided_at="2026-05-01")
    passage = Passage("rfc:x.md#a", doc.id, "The Data Tools team owns notebooks.")
    client = StubClient([{"subject": "area:notebooks", "predicate": "owned_by", "value": "team:data-tools", "text": "Notebooks are owned by Data Tools."}])
    usage = Usage()
    facts = asyncio.run(extract([passage], [doc], ENTITIES, model="stub", cache_dir=tmp_path, client=client, usage=usage))
    assert len(facts) == 1
    assert facts[0].valid_from == "2026-05-01"  # an RFC's facts hold from the day it was decided
    assert facts[0].authority == AUTHORITY["rfc"]
    again = asyncio.run(extract([passage], [doc], ENTITIES, model="stub", cache_dir=tmp_path, client=client))
    assert client.calls == 1 and again == facts  # the second run reads the cache


def test_select_passages_skips_evidence_kinds():
    batch = load_posthog(None, fetch=fixture_fetch)
    chosen = select_passages(batch, Entities.from_batch(batch))
    kinds = {d.id: d.kind for d in batch.docs}
    assert chosen and {kinds[p.doc_id] for p in chosen} <= {"handbook", "team_page", "rfc"}
    # The ownership statement ranks first.
    assert "owned by the Billing team" in chosen[0].text


def test_reingest_is_idempotent(graph, tmp_path):
    batch = load_posthog(None, fetch=fixture_fetch)
    entities = Entities.from_batch(batch)
    client = StubClient([{"subject": "topic:revenue-queries", "predicate": "contact_for", "value": "team:billing", "text": "Billing owns the revenue queries."}])
    ensure_schema(graph)
    counts = []
    for _ in range(2):
        write_batch(graph, batch)
        facts = asyncio.run(extract(select_passages(batch, entities), batch.docs, entities, model="stub", cache_dir=tmp_path, client=client))
        write_facts(graph, facts)
        counts.append(
            (
                graph.query("MATCH (n) RETURN count(n)").result_set[0][0],
                graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0],
                graph.query("MATCH (f:Fact) RETURN count(f)").result_set[0][0],
            )
        )
    assert counts[0] == counts[1]
    assert graph.query("MATCH (d:Document)-[:ABOUT]->(a:Area) RETURN d.id, a.slug").result_set == [["pull:40001", "notebooks"]]


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_extract_handbook_ownership_sentence(tmp_path):
    from canon.config import settings

    doc = Doc("handbook:contents/handbook/product/metrics.md", "handbook", "Product metrics", "https://posthog.com/handbook/product/metrics", "2026-09-02")
    passage = Passage(
        f"{doc.id}#r",
        doc.id,
        "Revenue\nThese queries are written and owned by the Billing team. They are standardised across products. "
        "If you are intending a change, please chat to the billing team first.",
    )
    entities = Entities(
        areas={"notebooks": "Notebooks", "billing": "Billing", "revenue-analytics": "Revenue analytics"},
        teams={"billing": "Billing", "data-tools": "Data Tools"},
        people={},
    )
    facts = asyncio.run(extract([passage], [doc], entities, model=settings().extract_model, cache_dir=tmp_path))
    assert facts, "expected at least one fact"
    assert any(f.value == "team:billing" for f in facts)
    assert all(f.valid_from == "2026-09-02" and f.authority == 1 for f in facts)
