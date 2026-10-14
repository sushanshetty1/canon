"""End-to-end asks against real models. Run with `uv run pytest -m live`; skipped without ANTHROPIC_API_KEY."""

import asyncio
import os

import pytest

from canon.answer.ask import ask
from canon.demo_seed import seed
from canon.graph.db import workspace_graph, workspace_graph_name

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"),
]


def _ask(graph, question):
    async def run():
        return [e async for e in ask(graph, question)]

    return asyncio.run(run())


def test_seeded_company_who_owns_session_replay(graph):
    seed(graph)
    events = _ask(graph, "Who owns session replay?")
    verdicts = [e for e in events if e["type"] == "verdict"]
    assert events[-1]["type"] == "done" and verdicts
    assert any(
        e["verdict"] == "verified" and any(s["value"] == "team:replay" for s in e["sources"]) for e in verdicts
    )
    assert not any(e["verdict"] == "verified" and any(s["value"] == "team:product-analytics" and s["current"] is False
                                                     and len(e["sources"]) == 1 for s in e["sources"]) for e in verdicts)


def test_posthog_who_owns_notebooks(db):
    if workspace_graph_name("posthog") not in db.list_graphs():
        pytest.skip("the posthog workspace has not been ingested")
    events = _ask(workspace_graph(db, "posthog"), "Who owns notebooks?")
    verdicts = [e for e in events if e["type"] == "verdict"]
    assert any(e["verdict"] == "verified" and any(s["kind"] == "ownership_map" for s in e["sources"]) for e in verdicts)
