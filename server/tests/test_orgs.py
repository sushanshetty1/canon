"""Private and organisation repositories: the second OAuth step, the repository list, workspaces from private and
organisation repositories, members and invites, and that nothing leaks outside a workspace. GitHub is mocked."""

from urllib.parse import parse_qs, urlparse

import pytest
from cloud_kit import OWNER, REPO, SLUG, make, sign_in, tc

from canon.api.accounts_routes import _state_cookie
from canon.api.app import create_app
from canon.api.limits import Limits
from canon.cloud import repos
from canon.demo_seed import seed

APP_LINK = "https://github.com/settings/connections/applications/cid"


def recording_ingest(seen: list):
    def ingest(graph, repo, token, report):
        seen.append((repo, token))
        graph.query("CREATE (:Document {id: 'doc:README.md'})")
        return {"counts": {"documents": 1}}

    return ingest


def scopes_of(db, accounts_graph, user_id):
    return db.select_graph(accounts_graph).query("MATCH (u:User {id: $id}) RETURN u.scopes", {"id": user_id}).result_set[0][0]


# ----- the second OAuth step ---------------------------------------------------------------------------------------


def test_sign_in_stays_minimal_and_connecting_asks_for_repo_and_read_org(db, accounts_graph):
    cloud, github = make(db, accounts_graph)
    client = tc(create_app(cloud=cloud))

    assert sign_in(client).headers["location"] == "/app/new"
    assert client.get("/api/me").json()["user"]["private_repos"] is False
    assert scopes_of(db, accounts_graph, "gh101") == "public_repo read:user"

    res = client.get("/auth/github", params={"access": "private", "next": "/app/new"}, follow_redirects=False)
    q = parse_qs(urlparse(res.headers["location"]).query)
    assert q["scope"] == ["read:user repo read:org"]
    # The state check holds for the second step too: a forged state is refused before GitHub is called.
    calls = len(github.calls)
    assert client.get("/auth/callback", params={"code": "code-alice-repo", "state": "forged"}).status_code == 400
    assert len(github.calls) == calls

    res = client.get("/auth/callback", params={"code": "code-alice-repo", "state": q["state"][0]}, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/app/new"
    assert client.get("/api/me").json()["user"]["private_repos"] is True
    assert scopes_of(db, accounts_graph, "gh101") == "read:org read:user repo"  # the token response's `scope`

    # Unticking the scopes on GitHub's page leaves the grant as it was, and the app is told.
    res = sign_in(client, "code-alice", access="private")
    assert res.headers["location"] == "/app/new?connect=incomplete"
    assert client.get("/api/me").json()["user"]["private_repos"] is False


def test_state_cookie_reads_old_and_new_formats():
    assert _state_cookie("abc.%2Fapp%2Fnew") == ("abc", "signin", "/app/new")  # set before the second step existed
    assert _state_cookie("abc.private.%2Fapp%2Fnew") == ("abc", "private", "/app/new")
    assert _state_cookie("abc.signin.%2Fapp%3Fx%3Da.b") == ("abc", "signin", "/app?x=a.b")
    assert _state_cookie("abc.evil.https%3A%2F%2Fevil.example") == ("abc", "signin", "/app")
    assert _state_cookie("") == ("", "signin", "/app")


# ----- the repository list -----------------------------------------------------------------------------------------


def test_repository_list_is_grouped_by_owner_searched_and_paged(db, accounts_graph):
    cloud, github = make(db, accounts_graph)
    client = tc(create_app(cloud=cloud))
    assert client.get("/api/github/repos").status_code == 401

    sign_in(client)
    body = client.get("/api/github/repos").json()
    assert body["connected"] is True and body["private"] is False
    assert [r["full_name"] for g in body["groups"] for r in g["repos"]] == [REPO]  # public ones only, before connecting

    sign_in(client, "code-alice-repo", access="private")
    res = client.get("/api/github/repos")
    body = res.json()
    assert "gho_" not in res.text  # the token stays on the server
    assert body["private"] is True and body["login"] == "alice"
    assert [(o["login"], o["kind"], o["count"]) for o in body["owners"]] == [("alice", "user", 1), ("acme", "org", 2), (OWNER, "user", 1)]
    assert [(g["owner"], g["you"], [r["name"] for r in g["repos"]]) for g in body["groups"]] == [
        ("alice", True, ["notes"]), ("acme", False, ["handbook", "secret"]), (OWNER, False, ["cli"]),
    ]
    assert [r["private"] for g in body["groups"] for r in g["repos"]] == [True, True, True, False]
    # GitHub was asked for the user's own, collaborator and organisation repositories, most recently pushed first.
    listed = [u for _, u in github.calls if "/user/repos" in u][-1]
    assert "affiliation=owner%2Ccollaborator%2Corganization_member" in listed and "sort=pushed" in listed

    found = client.get("/api/github/repos", params={"q": "hand"}).json()
    assert [r["full_name"] for g in found["groups"] for r in g["repos"]] == ["acme/handbook"]
    only = client.get("/api/github/repos", params={"owner": "acme"}).json()
    assert [g["owner"] for g in only["groups"]] == ["acme"] and only["total"] == 2

    # The list is kept briefly per user and grant, so searching and paging do not call GitHub again.
    calls = len(github.calls)
    client.get("/api/github/repos", params={"q": "notes"})
    assert len(github.calls) == calls

    rows, _ = repos.user_repos(cloud, type("U", (), {"id": "gh101", "scopes": "read:org read:user repo", "token": "gho_code-alice-repo"})())
    page = repos.repo_page(rows, "alice", page=2, size=2)
    assert page["pages"] == 2 and page["total"] == 4 and [r["full_name"] for g in page["groups"] for r in g["repos"]] == ["acme/secret", REPO]
    assert repos.repo_page(rows, "alice", page=9, size=2)["page"] == 2


def test_a_development_user_has_no_repository_list(db, accounts_graph):
    cloud, github = make(db, accounts_graph, dev_login=True)
    client = tc(create_app(cloud=cloud))
    client.get("/auth/dev-login", params={"login": "sam"}, follow_redirects=False)
    body = client.get("/api/github/repos").json()
    assert body["connected"] is False and body["groups"] == [] and github.calls == []


# ----- workspaces from private and organisation repositories -------------------------------------------------------


def test_private_and_organisation_repositories_make_private_workspaces(db, accounts_graph, made):
    seen = []
    cloud, _ = make(db, accounts_graph, ingest=recording_ingest(seen))
    alice = tc(create_app(cloud=cloud))
    sign_in(alice)

    refused = alice.post("/api/workspaces", json={"repo": "alice/notes"})
    assert refused.status_code == 422 and refused.json()["reason"] == "connect"
    assert "connect private and organisation repositories" in refused.json()["detail"]

    sign_in(alice, "code-alice-repo", access="private")
    made += ["alice-notes", "acme-handbook"]
    res = alice.post("/api/workspaces", json={"repo": "alice/notes"})
    assert res.status_code == 201 and res.json()["workspace"]["private"] is True
    assert alice.post("/api/workspaces", json={"repo": "acme/handbook"}).json()["workspace"]["slug"] == "acme-handbook"
    assert seen == [("alice/notes", "gho_code-alice-repo"), ("acme/handbook", "gho_code-alice-repo")]

    # An organisation that restricts OAuth apps: say so, and link to where access is requested.
    res = alice.post("/api/workspaces", json={"repo": "lockedco/plans"})
    body = res.json()
    assert res.status_code == 422 and body["reason"] == "org_restricted" and body["link"] == APP_LINK
    assert "lockedco organisation limits which OAuth apps" in body["detail"] and "—" not in body["detail"]
    # An organisation's repository GitHub hides without saying why: the restriction is the likely reason.
    body = alice.post("/api/workspaces", json={"repo": "acme/nothing"}).json()
    assert body["reason"] == "org_restricted" and "probably" in body["detail"] and body["link"] == APP_LINK
    assert alice.post("/api/workspaces", json={"repo": "alice/nothing"}).json()["reason"] == "missing"

    # Someone whose token cannot read the private repository cannot make a workspace from it.
    bob = tc(create_app(cloud=cloud))
    sign_in(bob, "code-bob-repo", access="private")
    assert bob.post("/api/workspaces", json={"repo": "alice/notes"}).status_code == 422


def test_retrying_opens_the_workspace_you_belong_to(db, accounts_graph, made):
    seen = []
    cloud, github = make(db, accounts_graph, ingest=recording_ingest(seen))
    alice = tc(create_app(cloud=cloud))
    sign_in(alice)
    made += [SLUG, f"{SLUG}-2"]
    assert alice.post("/api/workspaces", json={"repo": REPO}).status_code == 201

    # GitHub stops answering (a rate limit, a lapsed grant): a retry still opens the workspace, without asking it.
    github.repos.pop(REPO)
    calls = len(github.calls)
    for text in (REPO, REPO.upper(), f"https://github.com/{REPO}", f"git@github.com:{REPO}.git", SLUG):
        res = alice.post("/api/workspaces", json={"repo": text})
        assert res.status_code == 200 and res.json()["created"] is False and res.json()["workspace"]["slug"] == SLUG, text
    assert len(github.calls) == calls and len(seen) == 1

    # Two requests at once from the same person make one workspace.
    accounts = cloud.accounts()
    real = accounts.find_own
    stale = [True]

    def looked_before_the_other_request_finished(user_id, text):
        if stale.pop() if stale else False:
            return None
        return real(user_id, text)

    accounts.find_own = looked_before_the_other_request_finished
    try:
        workspace, created = accounts.create_workspace("gh101", REPO)
    finally:
        accounts.find_own = real
    assert (workspace["slug"], created) == (SLUG, False)
    assert [w["slug"] for w in accounts.workspaces_of("gh101")] == [SLUG]


def test_a_member_retrying_opens_the_shared_workspace(db, accounts_graph, made):
    cloud, _ = make(db, accounts_graph, ingest=recording_ingest([]))
    alice, bob = tc(create_app(cloud=cloud)), tc(create_app(cloud=cloud))
    sign_in(alice)
    made.append(SLUG)
    alice.post("/api/workspaces", json={"repo": REPO})
    alice.post(f"/api/w/{SLUG}/members", json={"login": "bob"})
    sign_in(bob, "code-bob")
    res = bob.post("/api/workspaces", json={"repo": REPO})
    assert res.status_code == 200 and res.json()["workspace"]["slug"] == SLUG and res.json()["workspace"]["role"] == "member"


# ----- privacy -----------------------------------------------------------------------------------------------------

ROUTES = [
    ("POST", "/ask", {"question": "Who owns notebooks?"}),
    ("GET", "/facts/f-1", None),
    ("GET", "/stats", None),
    ("GET", "/fixes", None),
    ("POST", "/fixes/x/approve", {"repo": "alice/notes"}),
    ("POST", "/fixes/x/dismiss", {"reason": "no"}),
    ("GET", "/areas", None),
    ("GET", "/areas/notebooks/people", None),
    ("GET", "/people/alice", None),
    ("GET", "/decisions", None),
    ("GET", "/decisions/d-1", None),
    ("GET", "/changes?since=2026-01-01", None),
    ("GET", "/changes", None),  # even a malformed request answers 404, not 422
    ("GET", "/changes/brief?since=2026-01-01", None),
    ("GET", "/jobs/latest", None),
    ("POST", "/sync", None),
    ("GET", "/members", None),
    ("POST", "/members", {"login": "bob"}),
    ("DELETE", "/members/alice", None),
]


def test_a_private_workspace_is_404_to_everyone_outside_it(db, accounts_graph, graph, made):
    seed(graph)
    cloud, _ = make(db, accounts_graph, ingest=recording_ingest([]))
    runs = []

    async def ask(g, q):
        runs.append(q)
        yield {"type": "done", "counts": {}}

    def app():
        a = create_app(graph_for=lambda ws: graph if ws == "alice-notes" else None, cloud=cloud, ask_fn=ask, limits=Limits())
        a.state.brief_fn = None
        return a

    alice, bob, anon = tc(app()), tc(app()), tc(app())
    sign_in(alice, "code-alice-repo", access="private")
    made.append("alice-notes")
    assert alice.post("/api/workspaces", json={"repo": "alice/notes"}).status_code == 201
    # Bob can read the repository's owner's other work and is signed in, but is not a member.
    sign_in(bob, "code-bob-repo", access="private")
    for method, path, body in ROUTES:
        res = bob.request(method, f"/api/w/alice-notes{path}", json=body)
        assert res.status_code == 404, (method, path, res.status_code)
        assert res.json() == {"detail": "No such workspace."}
        assert anon.request(method, f"/api/w/alice-notes{path}", json=body).status_code == 401, (method, path)
    assert runs == []
    assert [w["slug"] for w in bob.get("/api/workspaces").json()["own"]] == []
    # The owner reads it.
    assert alice.get("/api/w/alice-notes/stats").status_code == 200
    assert alice.get("/api/w/alice-notes/decisions").status_code == 200


def test_answers_are_shared_only_inside_one_workspace(db, accounts_graph, graph, made):
    seed(graph)
    cloud, _ = make(db, accounts_graph, ingest=recording_ingest([]))
    runs = []

    async def ask(g, q):
        runs.append(q)
        yield {"type": "claim", "index": 0, "text": "Secret plans.", "fact_ids": []}
        yield {"type": "done", "counts": {}}

    limits = Limits()
    slugs = {SLUG, f"{SLUG}-2"}
    app = lambda: create_app(graph_for=lambda ws: graph if ws in slugs else None, cloud=cloud, ask_fn=ask, limits=limits)  # noqa: E731
    alice, bob, carol = tc(app()), tc(app()), tc(app())
    sign_in(alice)
    sign_in(bob, "code-bob")
    sign_in(carol, "code-carol")
    made += [SLUG, f"{SLUG}-2"]
    alice.post("/api/workspaces", json={"repo": REPO})
    assert carol.post("/api/workspaces", json={"repo": REPO}).json()["workspace"]["slug"] == f"{SLUG}-2"

    question = {"question": "What are the plans?"}
    assert "Secret plans." in alice.post(f"/api/w/{SLUG}/ask", json=question).text and len(runs) == 1
    assert bob.post(f"/api/w/{SLUG}/ask", json=question).status_code == 404  # never reaches the cache
    assert carol.post(f"/api/w/{SLUG}/ask", json=question).status_code == 404
    # Carol's own workspace of the same repository is another workspace: her question is answered afresh.
    carol.post(f"/api/w/{SLUG}-2/ask", json=question)
    assert len(runs) == 2
    # A member of Alice's workspace shares its answers.
    alice.post(f"/api/w/{SLUG}/members", json={"login": "bob"})
    sign_in(bob, "code-bob")
    assert "Secret plans." in bob.post(f"/api/w/{SLUG}/ask", json=question).text and len(runs) == 2
    assert set(limits.cache) == {(SLUG, "what are the plans"), (f"{SLUG}-2", "what are the plans")}


# ----- members -----------------------------------------------------------------------------------------------------


def test_owner_invites_and_removes_members(db, accounts_graph, made):
    cloud, _ = make(db, accounts_graph, ingest=recording_ingest([]))
    alice, bob, carol = (tc(create_app(cloud=cloud)) for _ in range(3))
    sign_in(alice)
    sign_in(carol, "code-carol")  # signed in before she is invited
    made.append(SLUG)
    alice.post("/api/workspaces", json={"repo": REPO})

    res = alice.post(f"/api/w/{SLUG}/members", json={"login": "@Bob"})
    assert res.status_code == 200 and res.json()["status"] == "invited"
    assert [i["login"] for i in res.json()["invites"]] == ["bob"]
    assert alice.post(f"/api/w/{SLUG}/members", json={"login": "bob"}).json()["status"] == "invited"  # once
    assert alice.post(f"/api/w/{SLUG}/members", json={"login": "alice"}).json()["status"] == "member"
    assert alice.post(f"/api/w/{SLUG}/members", json={"login": "nobody-here"}).status_code == 422
    assert "organisation" in alice.post(f"/api/w/{SLUG}/members", json={"login": "acme"}).json()["detail"]
    assert alice.post(f"/api/w/{SLUG}/members", json={"login": "not a handle!"}).status_code == 422

    # Bob is not a member until he signs in.
    assert bob.get(f"/api/w/{SLUG}/stats").status_code == 401
    sign_in(bob, "code-bob")
    listed = bob.get(f"/api/w/{SLUG}/members").json()
    assert [(m["login"], m["role"], m["you"]) for m in listed["members"]] == [("alice", "owner", False), ("bob", "member", True)]
    assert listed["invites"] == []  # members see who belongs; only the owner sees open invites
    assert alice.get(f"/api/w/{SLUG}/members").json()["invites"] == []

    # Members cannot invite or remove others; the owner stays.
    assert bob.post(f"/api/w/{SLUG}/members", json={"login": "carol"}).status_code == 403
    assert bob.delete(f"/api/w/{SLUG}/members/alice").status_code == 403
    assert alice.delete(f"/api/w/{SLUG}/members/alice").status_code == 409

    # Someone already signed in joins the next time they open their workspaces.
    alice.post(f"/api/w/{SLUG}/members", json={"login": "carol"})
    assert [w["slug"] for w in carol.get("/api/workspaces").json()["own"]] == [SLUG]
    assert carol.delete(f"/api/w/{SLUG}/members/carol").json() == {"left": True}
    assert carol.get(f"/api/w/{SLUG}/stats").status_code == 404

    # Removed, Bob can no longer open it; a cancelled invite is gone.
    assert [m["login"] for m in alice.delete(f"/api/w/{SLUG}/members/bob").json()["members"]] == ["alice"]
    assert bob.get(f"/api/w/{SLUG}/stats").status_code == 404
    alice.post(f"/api/w/{SLUG}/members", json={"login": "carol"})
    assert alice.delete(f"/api/w/{SLUG}/members/carol").json()["invites"] == []
    assert alice.delete(f"/api/w/{SLUG}/members/carol").status_code == 404

    # Public workspaces have no members.
    assert alice.get("/api/w/demo/members").status_code == 403


def test_an_invite_belongs_to_the_account_not_the_handle(db, accounts_graph, made):
    cloud, github = make(db, accounts_graph, ingest=recording_ingest([]))
    github.profiles["impostor"] = {"id": 999, "login": "Bob", "name": "Not Bob", "type": "User"}
    alice, impostor = tc(create_app(cloud=cloud)), tc(create_app(cloud=cloud))
    sign_in(alice)
    made.append(SLUG)
    alice.post("/api/workspaces", json={"repo": REPO})
    alice.post(f"/api/w/{SLUG}/members", json={"login": "bob"})  # GitHub says bob is account 202
    sign_in(impostor, "code-impostor")  # a different account that took the handle
    assert impostor.get("/api/workspaces").json()["own"] == []
    assert impostor.get(f"/api/w/{SLUG}/stats").status_code == 404


# ----- sync ----------------------------------------------------------------------------------------------------------


def test_sync_reads_with_a_member_who_still_has_access(db, accounts_graph, made):
    seen = []
    cloud, github = make(db, accounts_graph, ingest=recording_ingest(seen))
    alice, bob = tc(create_app(cloud=cloud)), tc(create_app(cloud=cloud))
    sign_in(alice, "code-alice-repo", access="private")
    made.append("acme-handbook")
    alice.post("/api/workspaces", json={"repo": "acme/handbook"})
    alice.post("/api/w/acme-handbook/members", json={"login": "bob"})
    sign_in(bob, "code-bob-repo", access="private")

    assert alice.post("/api/w/acme-handbook/sync").status_code == 200
    assert seen[-1] == ("acme/handbook", "gho_code-alice-repo")  # their own token first

    github.readers["acme/handbook"] = {"bob"}  # Alice lost access to the repository
    assert alice.post("/api/w/acme-handbook/sync").status_code == 200
    assert seen[-1] == ("acme/handbook", "gho_code-bob-repo")

    github.readers["acme/handbook"] = set()
    res = alice.post("/api/w/acme-handbook/sync")
    assert res.status_code == 409 and res.json()["reason"] == "no_reader" and res.json()["link"] == APP_LINK
    assert "gho_" not in res.text and len(seen) == 3


@pytest.mark.parametrize("scopes, private", [("repo read:org read:user", True), ("public_repo read:user", False), ("repo", False), ("", False)])
def test_reads_private_needs_repo_and_read_org(scopes, private):
    from canon.cloud.accounts import normal_scopes, reads_private

    assert reads_private(normal_scopes(scopes.replace(" ", ","))) is private
