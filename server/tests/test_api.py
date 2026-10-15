import json

from fastapi.testclient import TestClient

from canon.api.app import create_app
from canon.demo_seed import fact_id, seed


def _client(graph, ask_fn=None):
    return TestClient(create_app(graph_for=lambda ws: graph if ws == "demo" else None, ask_fn=ask_fn))


def test_ask_streams_events(graph):
    seed(graph)
    seen = []

    async def stub(g, question):
        seen.append((g, question))
        yield {"type": "evidence", "facts": 1, "documents": 1}
        yield {"type": "claim", "index": 0, "text": "Replay owns session replay.", "fact_ids": []}
        yield {"type": "verdict", "index": 0, "verdict": "verified", "sources": [], "newer": [], "conflicting": []}
        yield {"type": "done", "counts": {"verified": 1, "stale": 0, "disputed": 0, "unsupported": 0}}

    res = _client(graph, stub).post("/api/w/demo/ask", json={"question": "  Who owns session replay? "})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    chunks = [c for c in res.text.split("\n\n") if c]
    assert all(c.startswith("data: ") for c in chunks)
    events = [json.loads(c.removeprefix("data: ")) for c in chunks]
    assert [e["type"] for e in events] == ["evidence", "claim", "verdict", "done"]
    assert seen == [(graph, "Who owns session replay?")]


def test_ask_failure_ends_with_an_error_event(graph):
    seed(graph)

    async def broken(g, question):
        yield {"type": "evidence", "facts": 1, "documents": 1}
        raise RuntimeError("boom")

    events = [json.loads(c[6:]) for c in _client(graph, broken).post("/api/w/demo/ask", json={"question": "x"}).text.split("\n\n") if c]
    assert events[-1]["type"] == "error" and "boom" not in events[-1]["message"]


def test_unknown_workspace_404(graph):
    client = _client(graph, lambda g, q: None)
    assert client.post("/api/w/nowhere/ask", json={"question": "Who?"}).status_code == 404
    assert client.post("/api/w/Bad%20Name/ask", json={"question": "Who?"}).status_code == 404
    # A graph with no documents is not a workspace yet.
    assert client.get("/api/w/demo/stats").status_code == 404


def test_question_is_required(graph):
    seed(graph)
    assert _client(graph, lambda g, q: None).post("/api/w/demo/ask", json={"question": ""}).status_code == 422


def test_fact_shows_its_chain_and_conflicts(graph):
    seed(graph)
    client = _client(graph)
    stale = fact_id("area:session-replay", "owned_by", "team:product-analytics", "handbook:handbook/session-replay.md#0")
    body = client.get(f"/api/w/demo/facts/{stale}").json()
    assert body["fact"]["stale"] is True and body["fact"]["title"] == "Session replay"
    assert body["fact"]["passage"].startswith("Session replay is owned by the Product analytics team")
    assert [f["value"] for f in body["forward"]] == ["team:replay"]
    assert body["forward"][0]["kind"] == "ownership_map" and body["forward"][0]["current"] is True

    now = body["forward"][0]["fact_id"]
    body = client.get(f"/api/w/demo/facts/{now}").json()
    assert body["forward"] == [] and {f["fact_id"] for f in body["back"]} >= {stale}
    assert any(f["kind"] == "team_page" for f in body["restated"])

    deploys = fact_id("topic:friday-deploys", "decided", "no deploys after 2pm on fridays",
                      "handbook:handbook/engineering/deployments.md#0")
    body = client.get(f"/api/w/demo/facts/{deploys}").json()
    assert [f["title"] for f in body["conflicts"]] == ["On-call"]
    assert client.get("/api/w/demo/facts/nope").status_code == 404


def test_stats(graph):
    seed(graph)
    body = _client(graph).get("/api/w/demo/stats").json()
    assert body["labels"]["Document"] == 9 and body["labels"]["Fact"] > 0
    assert body["stale_facts"] == 1 and body["stale_pages"] == 1 and body["disputes"] == 1


def test_ask_is_cached_and_limited(graph):
    from fastapi.testclient import TestClient

    from canon.api.app import create_app
    from canon.api.limits import Limits
    from canon.demo_seed import seed

    seed(graph)
    calls = []

    async def fake(g, q):
        calls.append(q)
        yield {"type": "evidence", "facts": 1, "documents": 1}
        yield {"type": "done", "counts": {}}

    client = TestClient(create_app(graph_for=lambda ws: graph, ask_fn=fake, limits=Limits(per_hour=1, per_day=10)))
    assert client.post("/api/w/demo/ask", json={"question": "Who owns replay?"}).status_code == 200
    assert client.post("/api/w/demo/ask", json={"question": "who owns replay"}).status_code == 200  # cached
    assert calls == ["Who owns replay?"]
    assert client.post("/api/w/demo/ask", json={"question": "Something new?"}).status_code == 429
