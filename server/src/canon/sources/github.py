"""A small GitHub client: a few git commands over a local partial clone, and the REST and GraphQL APIs.

Files and their history come from git, not the API: a blob-less clone with a sparse checkout costs one request and
can then answer "who last changed this file" and "what did it say at this commit" offline. Issues, pull requests and
reviews come from GraphQL, which returns a page of a hundred pull requests with their labels and reviewers in one
request. `GITHUB_TOKEN` is used when set and never logged. On a rate limit the client sleeps until the reset.

**Private repositories.** Inside `with git_token(token):` every git command sends the token to github.com as an
`http.extraHeader`, set through `GIT_CONFIG_COUNT` (the environment form of `git -c`). So the token is never in the
remote URL, never written to `.git/config`, never in the command line (which other local users can list), and never
in an error or a log. A blob-less clone fetches old file versions lazily, so `git show` needs the header as much as
`clone` and `fetch` do. Git never asks for a password: without access a command fails at once.
"""

import base64
import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

import httpx

API = "https://api.github.com"
GIT_HOST = "https://github.com/"
# Seconds a request may wait out a rate limit. Long batch fetches (the PostHog cache) can raise it.
MAX_WAIT = float(os.environ.get("CANON_GITHUB_MAX_WAIT", "120"))


class RateLimited(RuntimeError):
    pass


# ----- git over a local clone -------------------------------------------------------------------------------------

_token: ContextVar[str | None] = ContextVar("canon_git_token", default=None)


@contextmanager
def git_token(token: str | None) -> Iterator[None]:
    """Git commands in this block authenticate to github.com with `token` (a context variable, so a job in another
    thread keeps its own)."""
    reset = _token.set(token or None)
    try:
        yield
    finally:
        _token.reset(reset)


def git_env(token: str | None = None) -> dict[str, str]:
    """The environment git runs with: no prompts, and the token as a header for github.com only."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = token if token is not None else _token.get()
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.{GIT_HOST}.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        })
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=True, env=git_env())


def git(repo: Path, *args: str) -> str:
    return _run(["git", "-C", str(repo), *args]).stdout


def clone(url: str, dest: Path, *, sparse: list[str] | None = None) -> Path:
    """Clone once; a second call finds the clone and does nothing. `sparse` makes it a blob-less sparse clone."""
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if sparse:
        _run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", url, str(dest)])
        git(dest, "sparse-checkout", "set", "--no-cone", *sparse)
        git(dest, "checkout", "-q")
    else:
        _run(["git", "clone", "-q", url, str(dest)])
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


def file_commits(repo: Path, *paths: str) -> dict[str, list[Commit]]:
    """For every file under `paths` (all files when none): every commit that touched it, newest first."""
    out = git(repo, "log", "--name-only", f"--format=@@{_SEP}%H{_SEP}%aI{_SEP}%an{_SEP}%ae", "--", *paths)
    commits: dict[str, list[Commit]] = {}
    current: Commit | None = None
    for line in out.splitlines():
        if line.startswith("@@" + _SEP):
            current = _commit(line[3:])
        elif line and current:
            commits.setdefault(line, []).append(current)
    return commits


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def pull(repo: Path) -> str:
    """Bring a clone up to date with its remote's default branch. Returns the new head."""
    git(repo, "fetch", "-q", "origin")
    git(repo, "reset", "-q", "--hard", "FETCH_HEAD")
    return head(repo)


def changed_paths(repo: Path, old: str, new: str) -> list[str]:
    """Files that differ between two commits, renames as a delete and an add."""
    if old == new:
        return []
    return [p for p in git(repo, "diff", "--name-only", "--no-renames", old, new).splitlines() if p]


def handle_from_email(email: str) -> str | None:
    """`12345+octocat@users.noreply.github.com` -> `octocat`. Other addresses give nothing."""
    local, _, domain = email.partition("@")
    if domain != "users.noreply.github.com":
        return None
    handle = local.split("+", 1)[-1].lower()
    return None if not handle or handle.endswith("[bot]") else handle


def login_of(node: dict | None) -> str | None:
    """A GraphQL author node as a lowercase handle. Bots and deleted accounts give nothing."""
    if not node or node.get("__typename") == "Bot" or (node.get("login") or "").endswith("[bot]"):
        return None
    return (node.get("login") or "").lower() or None


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
                wait = self._wait(r)
                if wait > MAX_WAIT:  # a sync should fail and say why, not hang until the limit resets
                    raise RateLimited(f"GitHub's rate limit resets in {round(wait / 60)} minutes. Try again then.")
                time.sleep(wait)
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

    def paged(self, query: str, repo: str, key: str, keep, variables: dict | None = None) -> list[dict]:
        """Page through a repository's GraphQL connection `key`. `keep(node)` returns True to keep a node, False to
        skip it, None to stop."""
        owner, name = repo.split("/")
        rows, cursor = [], None
        while True:
            data = self.graphql(query, {"owner": owner, "name": name, "cursor": cursor, **(variables or {})})
            conn = data["repository"][key]
            for node in conn["nodes"]:
                verdict = keep(node)
                if verdict is None:
                    return rows
                if verdict:
                    rows.append(node)
            if not conn["pageInfo"]["hasNextPage"]:
                return rows
            cursor = conn["pageInfo"]["endCursor"]
