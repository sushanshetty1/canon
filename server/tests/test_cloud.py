"""Sign-in, sessions, workspace access, workspaces from a repository and their jobs. GitHub is mocked throughout."""

import json
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from canon.api.app import create_app
from canon.cloud import Cloud, CloudConfig, crypto, session
from canon.cloud.session import current_user
from canon.demo_seed import seed

SECRET = "s" * 40


class FakeGitHub:
    """The parts of GitHub sign-in and the repository API Canon calls."""

    def __init__(self):
        self.calls = []
        self.repos = {"cli/cli": {"full_name": "cli/cli", "private": False}, "acme/secret": {"full_name": "acme/secret", "private": True}}
        self.profiles = {"code-alice": {"id": 101, "login": "Alice", "name": "Alice Ng"}, "code-bob": {"id": 202, "login": "bob", "name": None}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, str(request.url)))
        url = request.url
        if url.path == "/login/oauth/access_token":
            code = parse_qs(request.content.decode())["code"][0]
            if code not in self.profiles:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(200, json={"access_token": f"gho_{code}", "scope": "public_repo,read:user"})
        if url.path == "/user":
            token = request.headers["authorization"].removeprefix("Bearer gho_")
            return httpx.Response(200, json=self.profiles[token])
        if url.path.startswith("/repos/"):
            repo = url.path.removeprefix("/repos/")
            return httpx.Response(200, json=self.repos[repo]) if repo in self.repos else httpx.Response(404, json={})
        return httpx.Response(404)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def accounts_graph(db):
    name = f"test_canon_accounts_{uuid.uuid4().hex[:12]}"
    yield name
    if name in db.list_graphs():
        db.select_graph(name).delete()


@pytest.fixture
def made(db):
    """Workspace graphs a test creates, deleted afterwards."""
    slugs = []
    yield slugs
    for slug in slugs:
        if f"canon_{slug}" in db.list_graphs():
            db.select_graph(f"canon_{slug}").delete()


def make(db, accounts_graph, *, ingest=None, dev_login=False, profile="dev", github=None, **config):
    github = github or FakeGitHub()
    cfg = CloudConfig(
        github_client_id="cid", github_client_secret="csecret", secret=SECRET, public_url="https://canon.test",
        accounts_graph=accounts_graph, dev_login=dev_login, profile=profile, **config,
    )
    cloud = Cloud(cfg, connect=lambda: db, http=github.client, runner=lambda fn: fn(), ingest=ingest)
    return cloud, github


def tc(app) -> TestClient:
    """A client over https, as the session cookie is Secure when the public URL is."""
    return TestClient(app, base_url="https://testserver")


def sign_in(client: TestClient, code="code-alice"):
    res = client.get("/auth/github", params={"next": "/app/new"}, follow_redirects=False)
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    return client.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)


# ----- sessions and tokens -----------------------------------------------------------------------------------------


def test_session_cookie_is_signed_and_expires():
    cookie = session.sign("gh101", SECRET, now=1000)
    assert session.verify(cookie, SECRET, now=1001) == "gh101"
    assert session.verify(cookie, "x" * 40, now=1001) is None
    assert session.verify(cookie.replace("gh101", "gh102"), SECRET, now=1001) is None
    assert session.verify(cookie, SECRET, now=1000 + session.MAX_AGE + 1) is None
    assert session.verify("garbage", SECRET) is None and session.verify(None, SECRET) is None


def test_tokens_are_sealed_at_rest():
    sealed = crypto.seal("gho_secret", SECRET)
    assert "gho_secret" not in sealed and sealed != crypto.seal("gho_secret", SECRET)  # a fresh nonce each time
    assert crypto.unseal(sealed, SECRET) == "gho_secret"
    assert crypto.unseal(sealed, "x" * 40) is None
    assert crypto.unseal(sealed[:-4] + "AAAA", SECRET) is None
    assert crypto.unseal("plain", SECRET) is None


def test_dev_login_can_never_be_on_in_prod():
    assert CloudConfig.from_env({"CANON_DEV_LOGIN": "1", "CANON_PROFILE": "prod"}).dev_login is False
    assert CloudConfig.from_env({"CANON_DEV_LOGIN": "1"}).dev_login is True
    # Production never invents a session secret; development makes a throwaway one.
    assert CloudConfig.from_env({"CANON_PROFILE": "prod"}).sessions is False
    assert CloudConfig.from_env({}).sessions is True
    assert CloudConfig.from_env({}).public_workspaces == ("posthog", "demo")


# ----- GitHub sign-in ----------------------------------------------------------------------------------------------


def test_github_sign_in(db, accounts_graph):
    cloud, github = make(db, accounts_graph)
    client = tc(create_app(cloud=cloud))

    res = client.get("/auth/github", params={"next": "/app/new"}, follow_redirects=False)
    assert res.status_code == 302
    url = urlparse(res.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "github.com" and q["scope"] == ["read:user public_repo"] and q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["https://canon.test/auth/callback"]
    assert "canon_oauth_state" in res.cookies

    # A state that does not match the cookie is refused before GitHub is called.
    assert client.get("/auth/callback", params={"code": "code-alice", "state": "forged"}).status_code == 400
    assert github.calls == []

    res = client.get("/auth/callback", params={"code": "code-alice", "state": q["state"][0]}, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/app/new"
    assert client.get("/api/me").json() == {"user": {"login": "alice", "name": "Alice Ng", "dev": False}, "signin": True, "dev_login": False}

    # The token is stored sealed, and `current_user` gives it back decrypted.
    stored = db.select_graph(accounts_graph).query("MATCH (u:User {id: 'gh101'}) RETURN u.token").result_set[0][0]
    assert stored.startswith("v1.") and "gho_code-alice" not in stored
    app = create_app(cloud=cloud)
    probe = APIRouter()

    @probe.get("/api/probe")
    def who(request: Request) -> dict:
        user = current_user(request)
        return {"login": user.login, "token": user.token} if user else {}

    app.include_router(probe)
    probing = tc(app)
    probing.cookies = client.cookies
    assert probing.get("/api/probe").json() == {"login": "alice", "token": "gho_code-alice"}

    assert client.post("/auth/logout").json() == {"ok": True}
    assert client.get("/api/me").json()["user"] is None


def test_failed_exchange_returns_to_the_app(db, accounts_graph):
    cloud, _ = make(db, accounts_graph)
    client = tc(create_app(cloud=cloud))
    res = sign_in(client, code="code-unknown")
    assert res.status_code == 302 and res.headers["location"] == "/app/new?signin=failed"
    assert client.get("/api/me").json()["user"] is None


def test_next_never_leaves_the_site(db, accounts_graph):
    cloud, _ = make(db, accounts_graph)
    client = tc(create_app(cloud=cloud))
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
        res = client.get("/auth/github", params={"next": bad}, follow_redirects=False)
        state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
        res = client.get("/auth/callback", params={"code": "code-alice", "state": state}, follow_redirects=False)
        assert res.headers["location"] == "/app"


def test_sign_in_off_without_an_oauth_app(db, accounts_graph):
    cloud, _ = make(db, accounts_graph, )
    cloud.config = CloudConfig(secret=SECRET, accounts_graph=accounts_graph)
    client = tc(create_app(cloud=cloud))
    assert client.get("/auth/github", follow_redirects=False).status_code == 503
    assert client.get("/api/me").json() == {"user": None, "signin": False, "dev_login": False}


def test_dev_login(db, accounts_graph):
    cloud, _ = make(db, accounts_graph)
    assert tc(create_app(cloud=cloud)).get("/auth/dev-login", follow_redirects=False).status_code == 404
    cloud, _ = make(db, accounts_graph, dev_login=True, profile="prod")
    assert tc(create_app(cloud=cloud)).get("/auth/dev-login", follow_redirects=False).status_code == 404

    cloud, _ = make(db, accounts_graph, dev_login=True)
    client = tc(create_app(cloud=cloud))
    res = client.get("/auth/dev-login", params={"login": "Sam", "next": "/app"}, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/app"
    assert client.get("/api/me").json()["user"] == {"login": "sam", "name": "sam", "dev": True}


# ----- workspace access --------------------------------------------------------------------------------------------


def test_public_workspaces_are_open_and_private_ones_are_members_only(db, accounts_graph, graph, made):
    seed(graph)
    cloud, _ = make(db, accounts_graph, ingest=lambda g, repo, token, report: {"counts": {}})
    graphs = {"demo": graph}

    def graph_for(ws):
        return graphs.get(ws)

    extra = APIRouter()  # a route another module adds later is checked the same way

    @extra.get("/api/w/{ws}/later")
    def later(ws: str) -> dict:
        return {"ws": ws}

    def app():
        a = create_app(graph_for=graph_for, cloud=cloud)
        a.include_router(extra)
        return a

    anon = tc(app())
    assert anon.get("/api/w/demo/stats").status_code == 200
    assert anon.get("/api/w/demo/later").status_code == 200

    alice = tc(app())
    sign_in(alice)
    made.append("cli-cli")
    assert alice.post("/api/workspaces", json={"repo": "cli/cli"}).status_code == 201
    graphs["cli-cli"] = graph  # the workspace's routes read this graph

    assert alice.get("/api/w/cli-cli/stats").status_code == 200
    assert alice.get("/api/w/cli-cli/later").json() == {"ws": "cli-cli"}
    assert anon.get("/api/w/cli-cli/stats").status_code == 401
    assert anon.post("/api/w/cli-cli/ask", json={"question": "Who?"}).status_code == 401
    assert anon.get("/api/w/cli-cli/later").status_code == 401
    assert anon.get("/api/w/cli-cli/jobs/latest").status_code == 401

    bob = tc(app())
    sign_in(bob, code="code-bob")
    assert bob.get("/api/w/cli-cli/stats").status_code == 404
    assert bob.get("/api/w/cli-cli/facts/x").status_code == 404
    assert bob.post("/api/w/cli-cli/sync").status_code == 404
    assert anon.get("/api/w/nowhere/stats").status_code == 404

    # Public workspaces are read-only, even to a signed-in user.
    assert alice.post("/api/w/demo/sync").status_code == 403
    assert anon.post("/api/w/demo/sync").status_code == 401


# ----- workspaces from a repository --------------------------------------------------------------------------------


def test_create_a_workspace_from_a_repository(db, accounts_graph, made):
    seen = []

    def ingest(graph, repo, token, report):
        seen.append((repo, token))
        report(step="docs", counts={"docs": 3})
        report(step="write", counts={"docs": 3, "documents": 9}, progress=0.4)
        graph.query("CREATE (:Document {id: 'doc:README.md'})")
        return {"counts": {"docs": 3, "documents": 9, "facts": 4}}

    cloud, _ = make(db, accounts_graph, ingest=ingest)
    client = tc(create_app(cloud=cloud))
    assert client.post("/api/workspaces", json={"repo": "cli/cli"}).status_code == 401

    sign_in(client)
    assert client.post("/api/workspaces", json={"repo": "not a repo"}).status_code == 422
    assert "public" in client.post("/api/workspaces", json={"repo": "acme/secret"}).json()["detail"]
    assert client.post("/api/workspaces", json={"repo": "acme/missing"}).status_code == 422

    made.append("cli-cli")
    res = client.post("/api/workspaces", json={"repo": "https://github.com/cli/cli"})
    assert res.status_code == 201
    body = res.json()
    assert body["workspace"] == {"slug": "cli-cli", "name": "cli/cli", "repo": "cli/cli", "public": False, "role": "owner"}
    assert body["job"]["status"] == "done" and body["job"]["kind"] == "create" and body["job"]["progress"] == 1.0
    assert body["job"]["counts"] == {"docs": 3, "documents": 9, "facts": 4}
    assert seen == [("cli/cli", "gho_code-alice")]  # read with the signed-in user's token

    # The same repository again is the same workspace, not a second one.
    again = client.post("/api/workspaces", json={"repo": "cli/cli"})
    assert again.status_code == 200 and again.json()["created"] is False and len(seen) == 1

    listed = client.get("/api/workspaces").json()
    assert [w["slug"] for w in listed["public"]] == ["posthog", "demo"]
    assert [w["slug"] for w in listed["own"]] == ["cli-cli"]
    assert listed["own"][0]["job"]["status"] == "done" and listed["own"][0]["suggestions"]
    assert tc(create_app(cloud=cloud)).get("/api/workspaces").json()["own"] == []

    # Another user making the same repository's workspace gets a slug of their own.
    bob = tc(create_app(cloud=cloud))
    sign_in(bob, code="code-bob")
    made.append("cli-cli-2")
    assert bob.post("/api/workspaces", json={"repo": "cli/cli"}).json()["workspace"]["slug"] == "cli-cli-2"


def test_workspace_limit(db, accounts_graph, made):
    github = FakeGitHub()
    for i in range(6):
        github.repos[f"acme/r{i}"] = {"full_name": f"acme/r{i}", "private": False}
    cloud, _ = make(db, accounts_graph, github=github, ingest=lambda g, repo, token, report: {})
    client = tc(create_app(cloud=cloud))
    sign_in(client)
    for i in range(5):
        made.append(f"acme-r{i}")
        assert client.post("/api/workspaces", json={"repo": f"acme/r{i}"}).status_code == 201
    assert client.post("/api/workspaces", json={"repo": "acme/r5"}).status_code == 409


def test_sync_and_job_progress(db, accounts_graph, made):
    runs = []
    pending = []

    def ingest(graph, repo, token, report):
        runs.append(repo)
        report(step="extract", counts={"extracted": 1, "to_extract": 4}, progress=0.5)
        if len(runs) == 3:
            raise httpx.ConnectError("https://x-access-token:gho_secret@github.com failed")
        return {"counts": {"documents": 2}}

    cloud, _ = make(db, accounts_graph, ingest=ingest)
    client = tc(create_app(cloud=cloud))
    sign_in(client)
    made.append("cli-cli")
    client.post("/api/workspaces", json={"repo": "cli/cli"})

    res = client.post("/api/w/cli-cli/sync")
    assert res.status_code == 200 and res.json()["job"]["kind"] == "sync" and runs == ["cli/cli", "cli/cli"]

    # A failure is stored as a calm sentence, never the error text (which can carry a token).
    client.post("/api/w/cli-cli/sync")
    job = client.get("/api/w/cli-cli/jobs/latest").json()["job"]
    assert job["status"] == "failed" and "gho_secret" not in json.dumps(job) and "GitHub" in job["error"]
    assert job["step"] == "extract" and job["counts"] == {"extracted": 1, "to_extract": 4}

    # One job at a time: while one runs, another is refused.
    cloud.runner = pending.append
    assert client.post("/api/w/cli-cli/sync").status_code == 200
    job = client.get("/api/w/cli-cli/jobs/latest").json()["job"]
    assert job["status"] == "running" and job["step_label"] == "Reading the repository"
    assert client.post("/api/w/cli-cli/sync").status_code == 409
    pending.pop()()
    assert client.get("/api/w/cli-cli/jobs/latest").json()["job"]["status"] == "done"


def test_a_job_left_running_by_a_stopped_server_reads_as_failed(db, accounts_graph, made):
    cloud, _ = make(db, accounts_graph, ingest=lambda g, r, t, report: {})
    client = tc(create_app(cloud=cloud))
    sign_in(client)
    made.append("cli-cli")
    cloud.runner = lambda fn: None  # the job never runs: the server "stopped"
    client.post("/api/workspaces", json={"repo": "cli/cli"})
    assert client.get("/api/w/cli-cli/jobs/latest").json()["job"]["status"] == "running"
    real = cloud.clock
    cloud.clock = lambda: real() + 3600
    cloud.jobs()._running.clear()
    assert client.get("/api/w/cli-cli/jobs/latest").json()["job"]["status"] == "failed"
    cloud.runner = lambda fn: fn()
    assert client.post("/api/w/cli-cli/sync").status_code == 200
