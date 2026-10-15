"""The connections API: credentials checked and sealed, syncs as jobs, removal, uploads, who may do what, and the
scheduler. Every service is answered from recorded responses; jobs run inline; no model is called."""

import io
import json
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

from canon.api.app import create_app
from canon.cloud import Cloud, CloudConfig, crypto
from canon.sources.connections import Connections, Scheduler
from recorded import Recorded

SECRET = "k" * 40


@pytest.fixture
def setup(db):
    accounts = f"test_canon_accounts_{uuid.uuid4().hex[:12]}"
    api = Recorded()
    cfg = CloudConfig(secret=SECRET, accounts_graph=accounts, dev_login=True, public_url="http://testserver")
    cloud = Cloud(cfg, connect=lambda: db, http=api.client, runner=lambda fn: fn())
    cloud.connector_models = lambda: {}  # no model in tests
    cloud.sleep = lambda _: None
    before = set(db.list_graphs())
    yield cloud, api
    for name in set(db.list_graphs()) - before:
        if name.startswith("canon_") or name == accounts:
            db.select_graph(name).delete()


def client(cloud, login="alice") -> TestClient:
    c = TestClient(create_app(cloud=cloud, graph_for=lambda ws: cloud.graph(ws)))
    if login:
        c.get(f"/auth/dev-login?login={login}", follow_redirects=False)
    return c


def workspace(c: TestClient) -> str:
    res = c.post("/api/workspaces/blank", json={"name": f"Kestrel {uuid.uuid4().hex[:6]}"})
    assert res.status_code == 201, res.text
    return res.json()["workspace"]["slug"]


def test_a_blank_workspace_belongs_to_its_maker(setup):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    own = c.get("/api/workspaces").json()["own"]
    assert [(w["slug"], w["repo"], w["role"]) for w in own] == [(slug, None, "owner")]
    assert client(cloud, None).post("/api/workspaces/blank", json={"name": "Nope"}).status_code == 401


def test_connecting_checks_the_credential_and_says_what_is_wrong(setup):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "slack", "secret": "xoxp-user-token"})
    assert res.status_code == 422 and "Bot User OAuth Token" in res.json()["detail"]
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "slack", "secret": "xoxb-wrong"})
    assert res.status_code == 422 and res.json()["detail"].startswith("Slack did not accept this token")
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "linear", "secret": "lin_api_wrong"})
    assert res.status_code == 422 and "Linear did not accept this API key" in res.json()["detail"]
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "jira", "config": {"site": "10.0.0.1"}, "secret": "x"})
    assert res.status_code == 422 and "email address" in res.json()["detail"]
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "jira", "config": {"site": "10.0.0.1", "email": "a@b.c"}, "secret": "x"})
    assert res.status_code == 422 and "Atlassian Cloud sites only" in res.json()["detail"]
    assert c.get(f"/api/w/{slug}/connections").json()["connections"] == []


def test_a_connection_syncs_into_the_graph_and_never_shows_its_secret(setup, db):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "slack", "secret": "xoxb-good", "config": {"max_channels": "5", "evil": 1}})
    assert res.status_code == 201, res.text
    conn = res.json()["connection"]
    assert conn["label"] == "Slack · Kestrel" and conn["config"] == {"max_channels": 5}
    assert conn["status"] == "ok" and conn["counts"]["documents"] == 4 and conn["last_synced_at"]
    assert any("groups:read" in n for n in conn["notes"])
    listing = c.get(f"/api/w/{slug}/connections").json()
    assert "xoxb-good" not in json.dumps(listing) and "secret" not in listing["connections"][0]
    assert listing["job"]["status"] == "done" and listing["job"]["connection"] == conn["id"]
    graph = cloud.graph(slug)
    stored = Connections(graph).raw(conn["id"])
    assert stored["secret"] != "xoxb-good" and crypto.unseal(stored["secret"], SECRET) == "xoxb-good"
    tagged = graph.query("MATCH (d:Document {connection: $id}) RETURN count(d), collect(DISTINCT d.kind)", {"id": conn["id"]}).result_set
    assert tagged[0][0] == 4 and tagged[0][1] == ["slack_thread"]
    # The person's Slack id is kept; their email is not, anywhere in the graph.
    rows = graph.query("MATCH (p:Person) RETURN p.handle, p.slack_id").result_set
    assert ("slack:u0ben", "U0BEN") in [tuple(r) for r in rows]
    everything = json.dumps(graph.query("MATCH (n) RETURN properties(n)").result_set)
    assert "kestrel.example" not in everything and "xoxb-good" not in everything
    # Ask works on the new workspace: it has documents now.
    assert c.get(f"/api/w/{slug}/stats").status_code == 200


def test_sync_now_reads_from_the_cursor(setup):
    cloud, api = setup
    c = client(cloud)
    slug = workspace(c)
    conn = c.post(f"/api/w/{slug}/connections", json={"kind": "notion", "secret": "ntn_good"}).json()["connection"]
    assert conn["counts"]["documents"] == 3
    res = c.post(f"/api/w/{slug}/connections/{conn['id']}/sync")
    assert res.status_code == 200 and res.json()["job"]["status"] == "done"
    stored = Connections(cloud.graph(slug)).raw(conn["id"])
    assert stored["cursor"] == "2026-10-13T08:30:00.000Z"
    assert c.post(f"/api/w/{slug}/connections/nope/sync").status_code == 404


def test_a_failed_sync_shows_why(setup):
    cloud, api = setup
    c = client(cloud)
    slug = workspace(c)
    conn = c.post(f"/api/w/{slug}/connections", json={"kind": "linear", "secret": "lin_api_good"}).json()["connection"]
    api.tokens["linear"] = "lin_api_rotated"  # the key was revoked after it was connected
    job = c.post(f"/api/w/{slug}/connections/{conn['id']}/sync").json()["job"]
    assert job["status"] == "failed" and job["error"].startswith("Linear did not accept this API key")
    after = c.get(f"/api/w/{slug}/connections").json()["connections"][0]
    assert after["status"] == "failed" and after["error"] == job["error"]


def test_atlassian_email_is_sealed_with_the_token(setup):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    res = c.post(f"/api/w/{slug}/connections", json={
        "kind": "jira", "config": {"site": "https://kestrel.atlassian.net/jira/software", "email": "ana@kestrel.example"}, "secret": "atl-good",
    })
    assert res.status_code == 201, res.text
    conn = res.json()["connection"]
    assert conn["config"] == {"site": "https://kestrel.atlassian.net"} and conn["status"] == "ok"
    assert "ana@kestrel.example" not in json.dumps(c.get(f"/api/w/{slug}/connections").json())
    sealed = Connections(cloud.graph(slug)).raw(conn["id"])["secret"]
    assert json.loads(crypto.unseal(sealed, SECRET)) == {"email": "ana@kestrel.example", "token": "atl-good"}
    res = c.post(f"/api/w/{slug}/connections", json={"kind": "confluence", "config": {"site": "kestrel", "email": "ana@kestrel.example"}, "secret": "atl-good"})
    assert res.status_code == 201 and res.json()["connection"]["counts"]["documents"] == 2


def test_removing_a_connection_keeps_or_deletes_its_documents(setup):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    graph = cloud.graph(slug)
    slack = c.post(f"/api/w/{slug}/connections", json={"kind": "slack", "secret": "xoxb-good"}).json()["connection"]
    notion = c.post(f"/api/w/{slug}/connections", json={"kind": "notion", "secret": "ntn_good"}).json()["connection"]
    assert c.delete(f"/api/w/{slug}/connections/{slack['id']}?documents=sometimes").status_code == 422
    res = c.delete(f"/api/w/{slug}/connections/{slack['id']}")
    assert res.status_code == 200 and res.json() == {"removed": slack["id"], "documents": 4, "kept": True}
    rows = graph.query("MATCH (d:Document {connection: $id}) RETURN d.removed_at, size([(d)-[:HAS]->() | 1]), size([(d)-[:HAD]->() | 1])",
                       {"id": slack["id"]}).result_set
    assert len(rows) == 4 and all(r[0] and r[1] == 0 and r[2] > 0 for r in rows)
    # The Notion row's owner fact goes with its documents when they are deleted.
    assert graph.query("MATCH (f:Fact {predicate: 'owned_by'}) RETURN count(f)").result_set[0][0] == 1
    res = c.delete(f"/api/w/{slug}/connections/{notion['id']}?documents=delete")
    assert res.json()["documents"] == 3
    assert graph.query("MATCH (d:Document {connection: $id}) RETURN count(d)", {"id": notion["id"]}).result_set[0][0] == 0
    assert graph.query("MATCH (f:Fact {predicate: 'owned_by'}) RETURN count(f)").result_set[0][0] == 0
    assert [x["id"] for x in c.get(f"/api/w/{slug}/connections").json()["connections"]] == []


def test_only_members_connect_and_public_workspaces_never(setup):
    cloud, _ = setup
    alice = client(cloud)
    slug = workspace(alice)
    body = {"kind": "slack", "secret": "xoxb-good"}
    assert client(cloud, "mallory").post(f"/api/w/{slug}/connections", json=body).status_code == 404
    assert client(cloud, "mallory").get(f"/api/w/{slug}/connections").status_code == 404
    assert client(cloud, None).post(f"/api/w/{slug}/connections", json=body).status_code == 401
    assert alice.post("/api/w/demo/connections", json=body).status_code == 403
    assert alice.post("/api/w/demo/files", files={"files": ("a.md", b"# A")}).status_code == 403
    assert alice.get("/api/w/demo/connections").json() == {"connections": [], "job": None, "can_connect": False}


def test_uploaded_files_are_read_into_the_workspace(setup):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("wiki/oncall.md", "# On-call\n\nThe Platform team runs the on-call rotation.")
    res = c.post(
        f"/api/w/{slug}/files",
        files=[("files", ("deploys.md", b"# Deploys\n\nWe deploy on weekdays.", "text/markdown")),
               ("files", ("wiki.zip", archive.getvalue(), "application/zip"))],
        data={"modified": json.dumps([1790000000000, 0])},
    )
    assert res.status_code == 202, res.text
    assert res.json()["job"]["status"] == "done"
    files = c.get(f"/api/w/{slug}/connections").json()["connections"][0]
    assert files["id"] == "files" and files["kind"] == "upload" and files["counts"]["documents"] == 2
    rows = dict(cloud.graph(slug).query("MATCH (d:Document {kind: 'upload'}) RETURN d.id, d.updated_at").result_set)
    assert rows == {"upload:deploys-md": "2026-09-21", "upload:wiki-wiki-oncall-md": rows["upload:wiki-wiki-oncall-md"]}
    assert c.post(f"/api/w/{slug}/connections/files/sync").status_code == 409
    assert c.post(f"/api/w/{slug}/files", data={"modified": "[]"}).status_code == 422


def test_run_connector_writes_dated_ticket_history_and_keeps_first_dates(graph):
    from dataclasses import replace

    from canon.sources.linear import LinearConnector
    from canon.sources.sync import run_connector

    api = Recorded()
    steps: list[str] = []
    out = run_connector(graph, LinearConnector("lin_api_good", http=api.client), connection_id="c1",
                        report=lambda step=None, **_: step and steps.append(step))
    assert list(dict.fromkeys(steps)) == ["read_linear", "write", "link"]
    assert out["cursor"] == "2026-10-14T11:00:00.000Z" and out["connection"]["documents"] == 3
    rows = graph.query(
        """MATCH (f:Fact {subject: 'topic:pay-12'})-[:VALUE]->(p:Person)
           RETURN p.name, f.valid_from, f.valid_to ORDER BY f.valid_from"""
    ).result_set
    assert [tuple(r) for r in rows] == [("Ben Okafor", "2026-09-21", "2026-10-02"), ("Cal Diaz", "2026-10-02", None)]
    lead = graph.query("MATCH (f:Fact {predicate: 'owned_by'})-[:ABOUT]->(a:Area) RETURN a.name, f.valid_from").result_set
    assert [tuple(r) for r in lead] == [("Billing migration", "2026-09-01")]

    # A later read that dates the same fact later (a source that cannot date it) keeps the first day.
    class Later:
        kind, label = "linear", "Linear"

        def read(self, *, cursor, report):
            result = LinearConnector("lin_api_good", http=api.client).read(cursor=None, report=report)
            result.batch.facts = [replace(f, valid_from="2026-10-20") for f in result.batch.facts]
            return result

    run_connector(graph, Later(), connection_id="c1")
    lead = graph.query("MATCH (f:Fact {predicate: 'owned_by'}) RETURN f.valid_from").result_set
    assert lead == [["2026-09-01"]]


def test_job_labels_name_the_connector_step(setup):
    from canon.cloud.jobs import _view

    assert _view({"status": "done", "step": "read_notion"}, 0)["step_label"] == "Reading Notion pages"
    assert _view({"status": "done", "step": "docs"}, 0)["step_label"] == "Reading documents"


def test_the_scheduler_syncs_connections_that_are_due(setup):
    cloud, _ = setup
    c = client(cloud)
    slug = workspace(c)
    conn = c.post(f"/api/w/{slug}/connections", json={"kind": "notion", "secret": "ntn_good"}).json()["connection"]
    c.post(f"/api/w/{slug}/files", files={"files": ("a.md", b"# A\n\nText.")})
    store = Connections(cloud.graph(slug))
    scheduler = Scheduler(cloud, 60)
    assert scheduler.tick() == []  # just synced
    store.update(conn["id"], last_tried_at="2026-01-01T00:00:00Z")
    assert scheduler.tick() == [(slug, conn["id"])]  # uploads are never re-synced on a schedule
    assert store.raw(conn["id"])["last_tried_at"] > "2026-01-01T00:00:00Z"
