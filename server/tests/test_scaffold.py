import pytest
from fastapi.testclient import TestClient

from canon.api.app import create_app
from canon.graph.db import ensure_schema, workspace_graph_name


def test_health_reports_graph_and_answers():
    body = TestClient(create_app()).get("/api/health").json()
    assert body["service"] == "canon" and body["graph"] in ("up", "down") and body["answers"] in ("on", "off")


def test_workspace_graph_names_are_checked():
    assert workspace_graph_name("posthog") == "canon_posthog"
    with pytest.raises(ValueError):
        workspace_graph_name("Bad Name")


def test_schema_is_idempotent(graph):
    ensure_schema(graph)
    ensure_schema(graph)
    labels = {r[0] for r in graph.query("CALL db.indexes() YIELD label RETURN label").result_set}
    assert {"Person", "Team", "Document", "Passage", "Fact"} <= labels
