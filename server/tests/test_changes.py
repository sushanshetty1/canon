import asyncio
import json

from decision_kit import PULLS, RFCS, seed_rfcs
from fastapi.testclient import TestClient
from kit import Kit

from canon.api.app import create_app
from canon.changes import brief, changes, evidence_for
from canon.decisions.build import build
from canon.verify.supersede import link

SINCE = "2026-09-01"


def company(graph):
    """Notebooks moved to Data tools; Product analytics stopped co-owning Replay; a handbook page fell out of date;
    two pages started to disagree about Friday deploys; a page stopped stating a fact; an RFC was accepted and
    replaced two older ones."""
    seed_rfcs(graph)
    k = Kit(graph)
    k.team("data-tools", "Data tools").team("product-analytics", "Product analytics").team("replay", "Replay")
    k.area("notebooks", "Notebooks").area("replay", "Replay")
    k.fact("own-nb-1", "area:notebooks", "owned_by", "team:product-analytics", kind="ownership_map", on="2026-01-01",
           valid_to="2026-09-10", doc="ownership_map:c1", text="notebooks: product-analytics")
    k.fact("own-rp-1", "area:replay", "owned_by", "team:replay", kind="ownership_map", on="2026-01-01",
           valid_to="2026-09-12", doc="ownership_map:c1", text="replay: replay, product-analytics")
    k.fact("own-rp-2", "area:replay", "owned_by", "team:product-analytics", kind="ownership_map", on="2026-01-01",
           valid_to="2026-09-12", doc="ownership_map:c1", text="replay: replay, product-analytics")
    k.fact("own-nb-2", "area:notebooks", "owned_by", "team:data-tools", kind="ownership_map", on="2026-09-10",
           doc="ownership_map:c2", text="notebooks: data-tools")
    k.fact("own-rp-3", "area:replay", "owned_by", "team:replay", kind="ownership_map", on="2026-09-12",
           doc="ownership_map:c3", text="replay: replay")
    k.fact("hb-nb", "area:notebooks", "owned_by", "team:product-analytics", on="2026-09-20", doc="handbook:notebooks",
           text="Product analytics owns notebooks.")
    k.fact("hb-fri-1", "topic:friday-deploys", "decided", "no deploys on fridays", on="2026-09-15", doc="handbook:deploys",
           text="Nobody deploys on Fridays.")
    k.fact("hb-fri-2", "topic:friday-deploys", "decided", "deploys any day", on="2026-09-18", doc="handbook:on-call",
           text="Deploys are fine on any day.")
    k.fact("hb-gone", "topic:standups", "process", "standups on mondays", on="2026-03-01", valid_to="2026-09-25",
           doc="handbook:rituals", text="Standups are on Mondays.")
    k.write()
    link(graph)
    build(graph, RFCS, PULLS)
    return graph


def _kinds(found):
    return sorted((c["kind"], c["title"]) for c in found["changes"])


def test_changes_since_a_date(graph):
    company(graph)
    found = changes(graph, SINCE)
    assert found["counts"] == {"ownership": 2, "decision": 3, "page": 1, "stale": 1, "dispute": 1}
    assert _kinds(found) == [
        ("decision", "Accepted: Project environments"),
        ("decision", "Flag environments was replaced by Project environments"),
        ("decision", "Flag folders was replaced by Project environments"),
        ("dispute", "Two sources disagree on friday deploys"),
        ("ownership", "Notebooks moved from Product analytics to Data tools"),
        ("ownership", "Product analytics no longer owns Replay"),
        ("page", "Rituals: 1 fact replaced"),
        ("stale", "Notebooks is out of date"),
    ]
    # Newest first, each with its facts and where it comes from.
    dates = [c["date"] for c in found["changes"]]
    assert dates == sorted(dates, reverse=True)
    moved = next(c for c in found["changes"] if c["title"].startswith("Notebooks moved"))
    assert moved["date"] == "2026-09-10" and moved["area"] == "notebooks"
    assert moved["fact_ids"] == ["own-nb-2", "own-nb-1"] and moved["sources"][0]["doc_id"] == "ownership_map:c2"
    stale = next(c for c in found["changes"] if c["kind"] == "stale")
    assert stale["date"] == "2026-09-20" and stale["fact_ids"] == ["hb-nb", "own-nb-2"]
    assert stale["detail"] == "About Notebooks: it says Product analytics, the ownership map says Data tools."
    assert [s["doc_id"] for s in stale["sources"]] == ["handbook:notebooks", "ownership_map:c2"]


def test_a_restated_owner_is_not_a_change(graph):
    company(graph)
    titles = [c["title"] for c in changes(graph, SINCE)["changes"]]
    assert not any("Replay now" in t or "moved from Replay" in t for t in titles)


def test_changes_after_a_later_date(graph):
    company(graph)
    found = changes(graph, "2026-09-16")
    assert found["counts"] == {"ownership": 0, "decision": 0, "page": 1, "stale": 1, "dispute": 1}
    assert changes(graph, "2026-10-30")["changes"] == []


def test_changes_about_an_area_or_a_team(graph):
    company(graph)
    by_area = changes(graph, SINCE, area="notebooks")
    assert _kinds(by_area) == [("ownership", "Notebooks moved from Product analytics to Data tools"),
                               ("stale", "Notebooks is out of date")]
    flags = changes(graph, SINCE, area="feature-flags")
    assert {c["kind"] for c in flags["changes"]} == {"decision"}
    # Replay owns the replay area, so the team sees that change; Data tools sees notebooks.
    assert [c["title"] for c in changes(graph, SINCE, team="replay")["changes"]] == ["Product analytics no longer owns Replay"]
    assert "Notebooks moved from Product analytics to Data tools" in [c["title"] for c in changes(graph, SINCE, team="data-tools")["changes"]]


def test_evidence_covers_every_kind(graph):
    company(graph)
    ev = evidence_for(graph, changes(graph, SINCE)["changes"])
    ids = {f["id"] for f in ev.facts}
    assert {"own-nb-1", "own-nb-2", "hb-nb", "hb-fri-1", "hb-fri-2", "hb-gone"} <= ids
    assert "decision:2025-01-10-flag-environments:replaced" in ids
    old = next(f for f in ev.facts if f["id"] == "own-nb-1")
    assert old["current"] is False and old["replaced_by"] == "own-nb-2"


class Drafter:
    def __init__(self, claims):
        self.claims = claims
        self.prompts = []

    async def json(self, system, prompt, schema):
        self.prompts.append(prompt)
        return {"claims": self.claims}


async def supported(text, facts):
    return {"supported": True, "past": False}


def _brief(graph, since, model):
    async def run():
        return [e async for e in brief(graph, since, model=model, entail=supported)]

    return asyncio.run(run())


def test_brief_streams_checked_claims_like_ask(graph):
    company(graph)
    drafter = Drafter([
        {"text": "Notebooks moved from Product analytics to Data tools on September 10.", "fact_ids": ["own-nb-1", "own-nb-2"]},
        {"text": "Pages disagree about Friday deploys.", "fact_ids": ["hb-fri-1", "hb-fri-2"]},
        {"text": "Product analytics owns notebooks.", "fact_ids": ["hb-nb"]},
        {"text": "Billing moved to Mars.", "fact_ids": ["made-up"]},
    ])
    events = _brief(graph, SINCE, drafter)
    assert [e["type"] for e in events[:5]] == ["evidence", "claim", "claim", "claim", "claim"]
    assert events[-1]["type"] == "done" and events[0]["facts"] > 0
    verdicts = {e["index"]: e["verdict"] for e in events if e["type"] == "verdict"}
    assert verdicts == {0: "verified", 1: "disputed", 2: "stale", 3: "unsupported"}
    assert events[-1]["counts"] == {"verified": 1, "stale": 1, "disputed": 1, "unsupported": 1}
    assert "What changed since 2026-09-01?" in drafter.prompts[0] and "[own-nb-2]" in drafter.prompts[0]


def test_brief_with_nothing_changed_is_empty(graph):
    company(graph)
    drafter = Drafter([])
    events = _brief(graph, "2026-10-30", drafter)
    assert events == [{"type": "evidence", "facts": 0, "documents": 0}, {"type": "empty", "ask": []}]
    assert drafter.prompts == []


# ----- the API ---------------------------------------------------------------------------------------------------


def _client(graph):
    app = create_app(graph_for=lambda ws: graph if ws == "demo" else None)
    return app, TestClient(app)


def test_decisions_api(graph):
    company(graph)
    _, client = _client(graph)
    body = client.get("/api/w/demo/decisions").json()
    assert body["counts"] == {"accepted": 2, "superseded": 2, "proposed": 1, "retired": 1}
    assert [d["id"] for d in body["decisions"]][0] == "2024-03-01-full-saml"  # oldest proposal first
    one = client.get("/api/w/demo/decisions/2025-01-10-flag-environments").json()
    assert one["status"] == "superseded" and one["superseded_by"][0]["title"] == "Project environments"
    assert client.get("/api/w/demo/decisions/nope").status_code == 404
    assert client.get("/api/w/nowhere/decisions").status_code == 404


def test_changes_api(graph):
    company(graph)
    _, client = _client(graph)
    body = client.get("/api/w/demo/changes", params={"since": SINCE, "area": "notebooks"}).json()
    assert body["since"] == SINCE and body["area"] == "notebooks" and len(body["changes"]) == 2
    assert client.get("/api/w/demo/changes", params={"since": "2026-13-01"}).status_code == 422
    assert client.get("/api/w/demo/changes", params={"since": "yesterday"}).status_code == 422
    assert client.get("/api/w/demo/changes").status_code == 422


def test_brief_api_streams_events(graph):
    company(graph)
    app, client = _client(graph)
    seen = []

    async def stub(g, since, *, area=None, team=None):
        seen.append((since, area, team))
        yield {"type": "evidence", "facts": 2, "documents": 1}
        yield {"type": "claim", "index": 0, "text": "Notebooks moved.", "fact_ids": []}
        raise RuntimeError("boom")

    app.state.brief_fn = stub
    res = client.get("/api/w/demo/changes/brief", params={"since": SINCE, "team": "replay"})
    assert res.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(c.removeprefix("data: ")) for c in res.text.split("\n\n") if c]
    assert [e["type"] for e in events] == ["evidence", "claim", "error"] and "boom" not in events[-1]["message"]
    assert seen == [(SINCE, None, "replay")]
