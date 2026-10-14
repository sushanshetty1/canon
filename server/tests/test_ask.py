import asyncio
import time

from kit import Kit

from canon.answer.ask import ask, who_to_ask
from canon.answer.draft import draft, prompt
from canon.answer.retrieve import Evidence, match_entities, retrieve, search_terms
from canon.demo_seed import seed
from canon.verify.supersede import link

OWNS = ("area:notebooks", "owned_by")


class StubModel:
    def __init__(self, claims):
        self.claims, self.prompts = claims, []

    async def json(self, system, prompt, schema):
        self.prompts.append(prompt)
        return {"claims": self.claims}


async def _yes(text, facts):
    return True


def _events(graph, question, model, entail=_yes):
    async def run():
        return [e async for e in ask(graph, question, model=model, entail=entail)]

    return asyncio.run(run())


def _notebooks(graph):
    k = Kit(graph)
    k.area("notebooks", "Notebooks").team("data-tools", "Data tools", members=["sam", "jonas"], leads=["jonas"])
    k.fact("old", *OWNS, "team:product-analytics", on="2026-03-01", text="Product analytics owns notebooks.")
    k.fact("map", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01", text="Data tools owns notebooks.")
    k.write()
    link(graph)


def test_search_terms_drop_stopwords_and_syntax():
    assert search_terms("Who owns session-replay? (now) | @team*") == ["owns", "session", "replay", "team"]


def test_retrieve_follows_supersession_to_current(graph):
    k = Kit(graph)
    k.fact("old", *OWNS, "team:product-analytics", on="2026-03-01", text="Product analytics builds the notebook feature.")
    k.fact("new", *OWNS, "team:data-tools", kind="ownership_map", on="2026-09-01", text="Moved: data-tools.")
    k.write()
    link(graph)
    # Only the old passage matches the words; the current fact comes in by following SUPERSEDED_BY.
    ev = retrieve(graph, "Which team builds the notebook feature?")
    by_id = {f["id"]: f for f in ev.facts}
    assert by_id["old"]["current"] is False and by_id["old"]["replaced_by"] == "new"
    assert by_id["new"]["current"] is True
    assert by_id["new"]["source"]["kind"] == "ownership_map" and by_id["new"]["source"]["url"]
    assert ev.documents == 2


def test_entities_prefer_the_longest_name(graph):
    seed(graph)
    assert match_entities(graph, "Who owns session replay?") == ["area:session-replay"]
    assert set(match_entities(graph, "What does the Replay team do?")) == {"team:replay"}


def test_ask_event_order(graph):
    _notebooks(graph)
    model = StubModel([
        {"text": "Data tools owns notebooks.", "fact_ids": ["map"]},
        {"text": "Product analytics owns notebooks.", "fact_ids": ["old"]},
        {"text": "Notebooks are written in Rust.", "fact_ids": ["invented"]},
    ])

    async def slow_first(text, facts):  # the first claim's check finishes last
        await asyncio.sleep(0.3 if text.startswith("Data") else 0.0)
        return True

    start = time.monotonic()
    events = _events(graph, "Who owns notebooks?", model, slow_first)
    assert time.monotonic() - start < 1.0
    types = [e["type"] for e in events]
    assert types == ["evidence", "claim", "claim", "claim", "verdict", "verdict", "verdict", "done"]
    assert events[0]["facts"] == 2 and events[0]["documents"] == 2
    verdicts = [e for e in events if e["type"] == "verdict"]
    assert verdicts[-1]["index"] == 0  # emitted when ready, not in claim order
    by_index = {e["index"]: e for e in verdicts}
    assert by_index[0]["verdict"] == "verified" and by_index[0]["sources"][0]["passage"]
    assert by_index[1]["verdict"] == "stale" and by_index[1]["newer"][0]["fact_id"] == "map"
    assert by_index[2]["verdict"] == "unsupported"
    assert events[-1]["counts"] == {"verified": 1, "stale": 1, "disputed": 0, "unsupported": 1}


def test_no_evidence_returns_no_answer(graph):
    _notebooks(graph)
    # Nothing in the graph matches: no draft is written, and no one is suggested.
    model = StubModel([{"text": "Made up.", "fact_ids": []}])
    events = _events(graph, "What is the parental leave policy?", model)
    assert events == [{"type": "evidence", "facts": 0, "documents": 0}, {"type": "empty", "ask": []}]
    assert model.prompts == []
    # The question names an area, but the facts found do not answer it: ask the lead of the team that owns it.
    events = _events(graph, "How long are notebooks kept after deletion?", StubModel([]))
    assert events[-1]["type"] == "empty"
    assert events[-1]["ask"] == [{"handle": "jonas", "name": "Jonas", "why": "Leads Data tools, which owns Notebooks."}]


def test_who_to_ask_falls_back_to_team_members(graph):
    k = Kit(graph)
    k.team("replay", "Replay", members=["lea", "mara"])
    k.write()
    people = who_to_ask(graph, ["team:replay"])
    assert {p["handle"] for p in people} == {"lea", "mara"} and people[0]["why"] == "On Replay."


def test_draft_labels_current_and_replaced(graph):
    _notebooks(graph)
    ev = retrieve(graph, "Who owns notebooks?")
    text = prompt("Who owns notebooks?", ev)
    assert "[map] (current;" in text and "[old] (replaced by map;" in text
    model = StubModel([{"text": "  ", "fact_ids": []}, {"text": "Data tools owns notebooks.", "fact_ids": ["map"]}])
    claims = asyncio.run(draft("Who owns notebooks?", ev, model=model))
    assert [(c.text, c.fact_ids) for c in claims] == [("Data tools owns notebooks.", ["map"])]


def test_demo_seed_has_the_cases(graph):
    counts = seed(graph)
    assert counts["stale"] == 1 and counts["contradicts"] == 1 and counts["stale_pages"] == 1
    assert seed(graph) == counts  # seeding again changes nothing
    ev = retrieve(graph, "Who owns session replay?")
    replay = [f for f in ev.facts if f["subject"] == "area:session-replay"]
    assert {f["value"] for f in replay if f["current"]} == {"team:replay"}
    assert any(f["stale"] and f["source"]["kind"] == "handbook" for f in replay)
    assert ev.facts[0]["subject"] == "area:session-replay"  # facts about the named area rank first
    assert who_to_ask(graph, ["area:billing"])[0]["name"] == "Ines Carvalho"


def test_empty_evidence_is_an_evidence_object():
    assert Evidence().documents == 0
