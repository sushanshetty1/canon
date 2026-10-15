"""A mocked GitHub and an app built on a throwaway accounts graph, for the sign-in and workspace tests.

`FakeGitHub` answers the calls Canon makes: the OAuth token exchange, `/user`, `/user/repos`, `/repos/{repo}`,
`/orgs/{org}`, `/user/memberships/orgs/{org}` and `/users/{login}`. Who can read what is modelled per token:

- a sign-in code `code-<name>` gives the token `gho_code-<name>`, granted `public_repo,read:user`;
- a code `code-<name>-repo` is the same account after connecting private repositories, granted
  `read:org,read:user,repo`;
- a private repository is visible only to `repo`-scoped tokens of the accounts in its `readers`;
- an organisation in `restricted` has OAuth app access restrictions: its private repositories are hidden (404) and
  its membership endpoint answers 403 with GitHub's message.
"""

import uuid
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from canon.cloud import Cloud, CloudConfig

SECRET = "s" * 40
# A repository name no real workspace has, so tests never touch a real workspace graph.
OWNER = f"t{uuid.uuid4().hex[:8]}"
REPO, SLUG = f"{OWNER}/cli", f"{OWNER}-cli"
RESTRICTED = (
    "Although you appear to have the correct authorization credentials, the `{org}` organization has enabled OAuth "
    "App access restrictions, meaning that data access to third-parties is limited."
)


def repo_record(full_name: str, *, private: bool = False, org: bool = False, pushed: str = "2026-10-01T00:00:00Z") -> dict:
    owner, name = full_name.split("/")
    return {
        "full_name": full_name, "name": name, "private": private, "description": f"About {name}", "pushed_at": pushed,
        "owner": {"login": owner, "type": "Organization" if org else "User"},
    }


class FakeGitHub:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.auth: list[str | None] = []  # the Authorization header of every API call
        self.profiles = {
            "alice": {"id": 101, "login": "Alice", "name": "Alice Ng", "type": "User"},
            "bob": {"id": 202, "login": "bob", "name": None, "type": "User"},
            "carol": {"id": 303, "login": "carol", "name": "Carol", "type": "User"},
        }
        self.repos = {
            REPO: repo_record(REPO),
            "acme/secret": repo_record("acme/secret", private=True, org=True),
            "alice/notes": repo_record("alice/notes", private=True, pushed="2026-10-10T00:00:00Z"),
            "acme/handbook": repo_record("acme/handbook", private=True, org=True, pushed="2026-10-09T00:00:00Z"),
            "lockedco/plans": repo_record("lockedco/plans", private=True, org=True),
        }
        self.readers = {"acme/secret": {"alice"}, "alice/notes": {"alice"}, "acme/handbook": {"alice", "bob"}, "lockedco/plans": {"alice"}}
        self.orgs = {"acme", "lockedco"}
        self.restricted = {"lockedco"}
        self.listed = ["alice/notes", "acme/handbook", "acme/secret", REPO]  # what /user/repos returns for alice

    # ----- who a token is

    def who(self, request: httpx.Request) -> tuple[str | None, bool]:
        """(account key, whether the token reads private repositories) for a request's token."""
        header = request.headers.get("authorization", "")
        self.auth.append(header or None)
        code = header.removeprefix("Bearer gho_code-") if header.startswith("Bearer gho_code-") else None
        if not code:
            return None, False
        name, _, extra = code.partition("-")
        return (name if name in self.profiles else None), extra == "repo"

    def can_read(self, repo: str, who: str | None, private_scope: bool) -> bool:
        record = self.repos.get(repo)
        if record is None:
            return False
        if not record["private"]:
            return True
        owner = repo.split("/")[0]
        return private_scope and who in self.readers.get(repo, set()) and owner not in self.restricted

    # ----- the API

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, str(request.url)))
        path = request.url.path
        if path == "/login/oauth/access_token":
            code = parse_qs(request.content.decode())["code"][0]
            name, _, extra = code.removeprefix("code-").partition("-")
            if not code.startswith("code-") or name not in self.profiles:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            scope = "read:org,read:user,repo" if extra == "repo" else "public_repo,read:user"
            return httpx.Response(200, json={"access_token": f"gho_{code}", "scope": scope, "token_type": "bearer"})
        who, private_scope = self.who(request)
        if path == "/user":
            return httpx.Response(200, json=self.profiles[who]) if who else httpx.Response(401, json={"message": "Bad credentials"})
        if path == "/user/repos":
            if not who:
                return httpx.Response(401, json={"message": "Bad credentials"})
            page = int(request.url.params.get("page", "1"))
            per = int(request.url.params.get("per_page", "30"))
            visible = [self.repos[r] for r in self.listed if self.can_read(r, who, private_scope)]
            return httpx.Response(200, json=visible[(page - 1) * per : page * per])
        if path.startswith("/repos/"):
            repo = path.removeprefix("/repos/")
            if self.can_read(repo, who, private_scope):
                return httpx.Response(200, json=self.repos[repo])
            return httpx.Response(404, json={"message": "Not Found"})
        if path.startswith("/orgs/"):
            org = path.removeprefix("/orgs/")
            return httpx.Response(200, json={"login": org}) if org in self.orgs else httpx.Response(404, json={"message": "Not Found"})
        if path.startswith("/user/memberships/orgs/"):
            org = path.removeprefix("/user/memberships/orgs/")
            if org in self.restricted:
                return httpx.Response(403, json={"message": RESTRICTED.format(org=org)})
            return httpx.Response(200, json={"state": "active"}) if org in self.orgs else httpx.Response(404, json={})
        if path.startswith("/users/"):
            login = path.removeprefix("/users/").lower()
            found = next((p for p in self.profiles.values() if p["login"].lower() == login), None)
            if login in self.orgs:
                found = {"id": 900, "login": login, "type": "Organization"}
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(404, json={"message": "Not Found"})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


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


def sign_in(client: TestClient, code="code-alice", *, access: str | None = None, next: str = "/app/new"):
    params = {"next": next, **({"access": access} if access else {})}
    res = client.get("/auth/github", params=params, follow_redirects=False)
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    return client.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
