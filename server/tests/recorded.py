"""Recorded responses for the connector APIs, served by one mocked transport. No test ever calls a real service.

`Recorded().client` is an `httpx.Client` factory over a `MockTransport` that answers Slack, Notion, Linear, Jira and
Confluence from the JSON in `fixtures/connectors/`, shaped exactly as each API documents its responses. `calls` keeps
every request; `fail` makes chosen requests fail (a 429 with Retry-After, a 401), to test what a connector does then.
"""

import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "connectors"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Recorded:
    def __init__(self):
        self.data = {k: load(k) for k in ("slack", "notion", "linear", "jira", "confluence")}
        self.calls: list[tuple[str, str, dict]] = []  # (method, url, headers)
        self.fail: dict[str, list[httpx.Response]] = {}  # path fragment -> responses to give first
        self.tokens = {"slack": "xoxb-good", "notion": "ntn_good", "linear": "lin_api_good"}
        self.atlassian = ("ana@kestrel.example", "atl-good")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url, dict(request.headers)))
        for fragment, queue in self.fail.items():
            if fragment in url and queue:
                return queue.pop(0)
        host = request.url.host
        if host == "slack.com":
            return self.slack(request)
        if host == "api.notion.com":
            return self.notion(request)
        if host == "api.linear.app":
            return self.linear(request)
        if host == "kestrel.atlassian.net":
            return self.atlassian_api(request)
        return httpx.Response(404, json={})

    # ----- Slack

    def slack(self, request: httpx.Request) -> httpx.Response:
        d = self.data["slack"]
        if request.headers.get("authorization") != f"Bearer {self.tokens['slack']}":
            return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
        method = request.url.path.removeprefix("/api/")
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if method == "auth.test":
            return httpx.Response(200, json=d["auth.test"], headers={"x-oauth-scopes": d["auth.test.scopes"]})
        if method == "conversations.list":
            if "private_channel" in q.get("types", "") and "groups:read" not in d["auth.test.scopes"]:
                return httpx.Response(200, json={"ok": False, "error": "missing_scope", "needed": "groups:read", "provided": d["auth.test.scopes"]})
            return httpx.Response(200, json=d["conversations.list"][1 if q.get("cursor") else 0])
        if method == "conversations.history":
            body = d["conversations.history"].get(q["channel"], {"ok": True, "messages": [], "has_more": False})
            oldest = float(q.get("oldest") or 0)
            body = {**body, "messages": [m for m in body["messages"] if float(m["ts"]) >= oldest]}
            return httpx.Response(200, json=body)
        if method == "conversations.replies":
            return httpx.Response(200, json=d["conversations.replies"][q["ts"]])
        if method == "users.info":
            return httpx.Response(200, json=d["users.info"].get(q["user"], {"ok": False, "error": "user_not_found"}))
        return httpx.Response(200, json={"ok": False, "error": "unknown_method"})

    # ----- Notion

    def notion(self, request: httpx.Request) -> httpx.Response:
        d = self.data["notion"]
        if request.headers.get("authorization") != f"Bearer {self.tokens['notion']}":
            return httpx.Response(401, json={"object": "error", "status": 401, "code": "unauthorized", "message": "API token is invalid."})
        assert request.headers.get("notion-version") == "2022-06-28"
        path = request.url.path.removeprefix("/v1/")
        if path == "users/me":
            return httpx.Response(200, json=d["users/me"])
        if path == "search":
            body = json.loads(request.content)
            return httpx.Response(200, json=d["search"][1 if body.get("start_cursor") else 0])
        if path.startswith("blocks/"):
            block = path.split("/")[1]
            return httpx.Response(200, json=d["blocks"].get(block, {"object": "list", "results": [], "has_more": False, "next_cursor": None}))
        if path.startswith("databases/"):
            return httpx.Response(200, json=d["databases"][path.split("/")[1]])
        if path.startswith("users/"):
            uid = path.split("/")[1]
            if uid in d["users"]:
                return httpx.Response(200, json=d["users"][uid])
            return httpx.Response(404, json={"object": "error", "status": 404, "code": "object_not_found"})
        return httpx.Response(404, json={})

    # ----- Linear

    def linear(self, request: httpx.Request) -> httpx.Response:
        d = self.data["linear"]
        if request.headers.get("authorization") != self.tokens["linear"]:
            return httpx.Response(400, json={"errors": [{"message": "Authentication required, not authenticated", "extensions": {"code": "AUTHENTICATION_ERROR"}}]})
        body = json.loads(request.content)
        query, variables = body["query"], body.get("variables") or {}
        if "viewer" in query:
            return httpx.Response(200, json=d["viewer"])
        for name in ("Teams", "Projects"):
            if query.startswith(f"query {name}"):
                return httpx.Response(200, json=d[name])
        if query.startswith("query Issues"):
            self.issue_filter = variables.get("filter")
            pages = d["Issues"]
            since = ((variables.get("filter") or {}).get("updatedAt") or {}).get("gt")
            page = pages[1] if variables.get("after") else pages[0]
            if since:
                nodes = [n for p in pages for n in p["data"]["issues"]["nodes"] if n["updatedAt"] > since]
                return httpx.Response(200, json={"data": {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
            return httpx.Response(200, json=page)
        return httpx.Response(400, json={"errors": [{"message": "Unknown query"}]})

    # ----- Jira and Confluence

    def atlassian_api(self, request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(":".join(self.atlassian).encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"errorMessages": ["Client must be authenticated to access this resource."]})
        path = request.url.path
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        j, c = self.data["jira"], self.data["confluence"]
        if path == "/rest/api/3/myself":
            return httpx.Response(200, json=j["myself"])
        if path == "/rest/api/3/project/search":
            return httpx.Response(200, json=j["project/search"])
        if path == "/rest/api/3/search/jql":
            self.last_jql = q.get("jql")
            return httpx.Response(200, json=j["search/jql"])
        if path == "/wiki/rest/api/user/current":
            return httpx.Response(200, json=c["user/current"])
        if path == "/wiki/api/v2/spaces":
            return httpx.Response(200, json=c["spaces"][1 if q.get("cursor") else 0])
        if path == "/wiki/api/v2/pages":
            return httpx.Response(200, json=c["pages"][1 if q.get("cursor") else 0])
        if path == "/wiki/api/v2/users-bulk":
            return httpx.Response(200, json=c["users-bulk"])
        return httpx.Response(404, json={})


def host_of(url: str) -> str:
    return urlparse(url).hostname or ""
