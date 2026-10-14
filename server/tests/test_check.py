import asyncio

from kit import Kit

from canon.graph.writer import write_batch
from canon.types import Batch, Doc, Passage
from canon.verify.check import Claim, check, check_graph, make_entail
from canon.verify.supersede import link

OWNS = ("area:notebooks", "owned_by")


def _company(graph):
    k = Kit(graph)
    k.fact("map-old", *OWNS, "team:product-analytics", kind="ownership_map", on="2026-02-01",
           text="Notebooks are owned by Product analytics.")
    k.fact("map", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01",
           text="Notebooks are owned by Data tools.")
    k.fact("handbook", *OWNS, "team:product-analytics", on="2026-10-01",
           text="Product analytics owns notebooks.")
    k.fact("a", "topic:friday-deploys", "policy", "no deploys after 2pm", on="2026-09-10",
           text="There are no deploys after 2pm on Fridays.")
    k.fact("b", "topic:friday-deploys", "policy", "deploy any day", on="2026-09-24",
           text="Deploys are allowed on any day.")
    k.write()
    link(graph)
    return k


def _entail(answer: bool, calls: list | None = None):
    async def entail(text, facts):
        if calls is not None:
            calls.append((text, facts))
        return answer

    return entail


def test_unknown_fact_is_unsupported(graph):
    _company(graph)
    calls = []
    out = asyncio.run(check(graph, Claim("Notebooks are owned by Data tools.", ["made-up"]), entail=_entail(True, calls)))
    assert out.verdict == "unsupported" and out.sources == []
    assert calls == []  # nothing to check it against, so no model is asked


def test_claim_without_facts_is_unsupported(graph):
    _company(graph)
    assert check_graph(graph, Claim("Notebooks are owned by Data tools.", [])).verdict == "unsupported"


def test_verdict_verified_has_sources(graph):
    _company(graph)
    out = check_graph(graph, Claim("Data tools owns notebooks.", ["map", "made-up"]))
    assert out.verdict == "verified"
    [s] = out.sources
    assert s["fact_id"] == "map" and s["fact"] == "Notebooks are owned by Data tools."
    assert s["passage"] == "Notebooks are owned by Data tools."
    assert s["title"] and s["url"].startswith("https://") and s["kind"] == "ownership_map" and s["date"] == "2026-09-01"


def test_verdict_stale_names_newer_fact(graph):
    _company(graph)
    for cited in ("handbook", "map-old"):
        out = check_graph(graph, Claim("Product analytics owns notebooks.", [cited]))
        assert out.verdict == "stale"
        assert [n["fact_id"] for n in out.newer] == ["map"]
        assert out.newer[0]["kind"] == "ownership_map" and out.newer[0]["passage"]


def test_claim_about_the_change_is_verified(graph):
    _company(graph)
    out = check_graph(graph, Claim("Notebooks moved from Product analytics to Data tools.", ["map-old", "map"]))
    assert out.verdict == "verified" and len(out.sources) == 2


def test_verdict_disputed(graph):
    _company(graph)
    out = check_graph(graph, Claim("There are no deploys after 2pm on Fridays.", ["a"]))
    assert out.verdict == "disputed"
    assert [c["fact_id"] for c in out.conflicting] == ["b"]
    assert out.conflicting[0]["passage"] == "Deploys are allowed on any day."


def test_disputed_claim_is_checked_with_both_sides(graph):
    _company(graph)
    calls = []
    out = asyncio.run(check(graph, Claim("The sources disagree about Friday deploys.", ["a"]), entail=_entail(True, calls)))
    assert out.verdict == "disputed"
    facts = calls[0][1]
    assert any("any day" in f for f in facts) and facts[-1] == "The graph records that these current sources disagree."


def test_closed_fact_is_stale(graph):
    k = Kit(graph)
    k.fact("gone", "topic:notebook-sharing", "process", "share by link", doc="handbook:notebooks", on="2026-05-01")
    k.write()
    doc = Doc("handbook:notebooks", "handbook", "Notebooks", "https://example.com/n", "2026-10-01")
    write_batch(graph, Batch(docs=[doc], passages=[Passage("handbook:notebooks#9", doc.id, "Something else.")]))
    link(graph)
    out = check_graph(graph, Claim("Notebooks are shared by link.", ["gone"]))
    assert out.verdict == "stale" and out.newer == [] and out.sources[0]["removed"]


def test_entailment_failure_is_unsupported(graph):
    _company(graph)
    calls = []
    out = asyncio.run(check(graph, Claim("Data tools has owned notebooks since 2019.", ["map"]), entail=_entail(False, calls)))
    assert out.verdict == "unsupported"
    assert calls and "Notebooks are owned by Data tools." in calls[0][1][0] and "2026-09-01" in calls[0][1][0]
    assert asyncio.run(check(graph, Claim("Data tools owns notebooks.", ["map"]), entail=_entail(True))).verdict == "verified"


def test_make_entail_reads_the_schema():
    class Stub:
        async def json(self, system, prompt, schema):
            assert schema["required"] == ["supported"] and "Sentence: S" in prompt and "- F" in prompt
            return {"supported": True}

    assert asyncio.run(make_entail(Stub())("S", ["F"])) is True
