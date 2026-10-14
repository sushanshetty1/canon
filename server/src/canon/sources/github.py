"""A small GitHub client: a few git commands over a local partial clone, and the REST and GraphQL APIs.

Files and their history come from git, not the API: a blob-less clone with a sparse checkout costs one request and
can then answer "who last changed this file" and "what did it say at this commit" offline. Issues, pull requests and
reviews come from GraphQL, which returns a page of a hundred pull requests with their labels and reviewers in one
request. `GITHUB_TOKEN` is used when set and never logged. On a rate limit the client sleeps until the reset.
"""

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

API = "https://api.github.com"


# ----- git over a local clone -------------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return out.stdout


def clone(url: str, dest: Path, *, sparse: list[str] | None = None) -> Path:
    """Clone once; a second call finds the clone and does nothing. `sparse` makes it a blob-less sparse clone."""
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if sparse:
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", url, str(dest)], check=True)
        git(dest, "sparse-checkout", "set", "--no-cone", *sparse)
        git(dest, "checkout", "-q")
    else:
        subprocess.run(["git", "clone", "-q", url, str(dest)], check=True)
    return dest


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str  # ISO 8601 with offset
    name: str
    email: str


_SEP = "\x1f"


def _commit(line: str) -> Commit:
    sha, date, name, email = line.split(_SEP)
    return Commit(sha, date, name, email)


def file_history(repo: Path, path: str) -> list[Commit]:
    """Every commit that touched `path`, oldest first."""
    out = git(repo, "log", "--reverse", f"--format=%H{_SEP}%aI{_SEP}%an{_SEP}%ae", "--", path)
    return [_commit(line) for line in out.splitlines() if line]


def first_and_last_commits(repo: Path, prefix: str) -> dict[str, tuple[Commit, Commit]]:
    """For every file under `prefix`: its first and its last commit, from one pass over the log."""
    out = git(repo, "log", "--name-only", f"--format=@@{_SEP}%H{_SEP}%aI{_SEP}%an{_SEP}%ae", "--", prefix)
    last: dict[str, Commit] = {}
    first: dict[str, Commit] = {}
    current: Commit | None = None
    for line in out.splitlines():
        if line.startswith("@@" + _SEP):
            current = _commit(line[3:])
        elif line and current:
            last.setdefault(line, current)  # the log is newest first
            first[line] = current
    return {path: (first[path], last[path]) for path in last}


def show(repo: Path, sha: str, path: str) -> str:
    return git(repo, "show", f"{sha}:{path}")


def handle_from_email(email: str) -> str | None:
    """`12345+octocat@users.noreply.github.com` -> `octocat`. Other addresses give nothing."""
    local, _, domain = email.partition("@")
    if domain != "users.noreply.github.com":
        return None
    handle = local.split("+", 1)[-1].lower()
    return None if not handle or handle.endswith("[bot]") else handle


# ----- the API ----------------------------------------------------------------------------------------------------


class GitHub:
    def __init__(self, token: str | None = None, client: httpx.Client | None = None):
        token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "canon"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = client or httpx.Client(headers=headers, timeout=60)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(8):
            try:
                r = self.http.request(method, url, **kwargs)
            except httpx.TransportError:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (403, 429) and ("rate limit" in r.text.lower() or r.headers.get("retry-after")):
                time.sleep(self._wait(r))
                continue
            if r.status_code in (502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r

    @staticmethod
    def _wait(r: httpx.Response) -> float:
        if r.headers.get("retry-after"):
            return float(r.headers["retry-after"]) + 1
        reset = r.headers.get("x-ratelimit-reset")
        return max(5.0, float(reset) - time.time() + 2) if reset else 60.0

    def get(self, path: str, **params) -> httpx.Response:
        return self._request("GET", f"{API}{path}", params=params)

    def paginate(self, path: str, *, limit: int | None = None, **params) -> list[dict]:
        rows: list[dict] = []
        params = {"per_page": 100, **params}
        url: str | None = f"{API}{path}"
        while url:
            r = self._request("GET", url, params=params)
            rows.extend(r.json())
            if limit and len(rows) >= limit:
                return rows[:limit]
            url = r.links.get("next", {}).get("url")
            params = {}  # the next link carries them
        return rows

    def graphql(self, query: str, variables: dict) -> dict:
        for attempt in range(6):
            r = self._request("POST", f"{API}/graphql", json={"query": query, "variables": variables})
            body = r.json()
            errors = body.get("errors") or []
            if any(e.get("type") == "RATE_LIMITED" for e in errors):
                time.sleep(60)
                continue
            if errors and not body.get("data"):
                raise RuntimeError(f"GitHub GraphQL error: {errors[0].get('message')}")
            return body["data"]
        raise RuntimeError("GitHub GraphQL kept rate limiting")
