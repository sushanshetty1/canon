"""What a signed-in user's GitHub token can read: their repositories, one repository, and which member of a
workspace can still read its repository.

Every call here is made by the server with the user's token. The token never reaches the browser, and nothing it
returns is shared with another user: the repository list is kept in memory for two minutes, per user and per grant.

When GitHub hides an organisation's repository, the reason is often that the organisation restricts OAuth apps: an
organisation owner has to approve Canon first. GitHub's answer is a 404 (or a 403 that says so), so a refusal for an
organisation's repository says this and links to the page where the user can request that approval,
`https://github.com/settings/connections/applications/<client id>`.
"""

from fastapi.responses import JSONResponse

from canon.cloud.crypto import unseal

API = "https://api.github.com"
LIST_TTL = 120.0
LIST_PAGES = 5  # at most 500 repositories, most recently pushed first
PAGE_SIZE = 15
AFFILIATION = "owner,collaborator,organization_member"


class Refusal(Exception):
    """A repository Canon may not read, with the reason in words, a short code for the app, and a link to fix it."""

    def __init__(self, status: int, message: str, reason: str, link: str | None = None):
        super().__init__(message)
        self.status, self.message, self.reason, self.link = status, message, reason, link

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content={"detail": self.message, "reason": self.reason, "link": self.link})


def app_access_url(cloud) -> str | None:
    """Where on GitHub a user grants or requests Canon's access to their organisations."""
    cid = cloud.config.github_client_id
    return f"https://github.com/settings/connections/applications/{cid}" if cid else None


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "canon", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _message(r) -> str:
    try:
        body = r.json()
    except Exception:
        return ""
    return str(body.get("message") or "") if isinstance(body, dict) else ""


def _rate_limited(r) -> bool:
    return r.status_code in (403, 429) and (r.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in _message(r).lower())


def _restricted(r) -> bool:
    return r.status_code == 403 and "oauth app access restrictions" in _message(r).lower()


def _get(cloud, path: str, token: str | None, params: dict | None = None):
    try:
        with cloud.http() as client:
            return client.get(f"{API}{path}", params=params, headers=_headers(token))
    except Exception:
        raise Refusal(502, "GitHub could not be reached. Try again in a moment.", "unreachable") from None


# ----- the user's repositories -------------------------------------------------------------------------------------


def _row(r: dict) -> dict:
    owner = r.get("owner") or {}
    return {
        "full_name": r.get("full_name"),
        "owner": (owner.get("login") or "").lower(),
        "owner_kind": "org" if owner.get("type") == "Organization" else "user",
        "name": r.get("name"),
        "private": bool(r.get("private")),
        "description": (r.get("description") or "")[:200],
        "pushed_at": r.get("pushed_at"),
        "archived": bool(r.get("archived")),
    }


def user_repos(cloud, user, *, refresh: bool = False) -> tuple[list[dict], bool]:
    """The repositories the user's token lists, most recently pushed first, and whether the list was cut short."""
    cache = cloud.repo_lists
    key = (user.id, user.scopes)
    hit = cache.get(key)
    if hit and not refresh and cloud.clock() - hit[0] < LIST_TTL:
        return hit[1], hit[2]
    rows: list[dict] = []
    truncated = False
    for page in range(1, LIST_PAGES + 1):
        r = _get(cloud, "/user/repos", user.token, {"affiliation": AFFILIATION, "sort": "pushed", "per_page": 100, "page": page})
        if r.status_code == 401:
            raise Refusal(409, "GitHub no longer accepts Canon's access to your account. Sign in again.", "reauth")
        if _rate_limited(r):
            raise Refusal(429, "GitHub's rate limit was reached. Try again in a few minutes.", "rate_limit")
        if r.status_code != 200:
            raise Refusal(502, "GitHub did not answer. Try again in a moment.", "unreachable")
        body = r.json()
        batch = body if isinstance(body, list) else []
        rows += [_row(x) for x in batch if isinstance(x, dict) and x.get("full_name")]
        if len(batch) < 100:
            break
        truncated = page == LIST_PAGES
    for k in [k for k in cache if k[0] == user.id]:  # a new grant replaces the old list
        cache.pop(k, None)
    cache[key] = (cloud.clock(), rows, truncated)
    return rows, truncated


def owners_of(rows: list[dict], login: str) -> list[dict]:
    """Owners in the order the app shows them: the user, then each organisation, then other people, each in the
    order of their most recent push."""
    seen: dict[str, dict] = {}
    for r in rows:
        o = seen.setdefault(r["owner"], {"login": r["owner"], "kind": r["owner_kind"], "count": 0})
        o["count"] += 1
    order = list(seen.values())
    rank = lambda o: 0 if o["login"] == login else 1 if o["kind"] == "org" else 2  # noqa: E731
    return sorted(order, key=rank)  # sorted is stable: push order holds within each rank


def repo_page(rows: list[dict], login: str, *, q: str = "", owner: str = "", page: int = 1, size: int = PAGE_SIZE) -> dict:
    """One page of the list, searched and filtered, grouped by owner in `owners_of` order."""
    owners = owners_of(rows, login)
    rank = {o["login"]: i for i, o in enumerate(owners)}
    words = q.lower().split()
    found = [
        r for r in rows
        if (not owner or r["owner"] == owner.lower())
        and all(w in f"{r['full_name']} {r['description']}".lower() for w in words)
    ]
    found.sort(key=lambda r: rank.get(r["owner"], 99))  # stable: most recently pushed first within an owner
    pages = max(1, -(-len(found) // size))
    page = min(max(1, page), pages)
    shown = found[(page - 1) * size : page * size]
    groups: list[dict] = []
    for r in shown:
        if not groups or groups[-1]["owner"] != r["owner"]:
            groups.append({"owner": r["owner"], "kind": r["owner_kind"], "you": r["owner"] == login, "repos": []})
        groups[-1]["repos"].append(r)
    return {"owners": owners, "groups": groups, "page": page, "pages": pages, "total": len(found), "size": size}


# ----- one repository ----------------------------------------------------------------------------------------------


def check_repo(cloud, repo: str, user) -> dict:
    """The repository's API record when the user's token can read it, public or private; else a Refusal saying why
    and, for an organisation that restricts OAuth apps, where to ask for access."""
    r = _get(cloud, f"/repos/{repo}", user.token)
    if r.status_code == 200:
        return r.json()
    if r.status_code == 401:
        raise Refusal(409, "GitHub no longer accepts Canon's access to your account. Sign in again.", "reauth")
    if _rate_limited(r):
        raise Refusal(429, "GitHub's rate limit was reached. Try again in a few minutes.", "rate_limit")
    if r.status_code not in (403, 404):
        raise Refusal(502, "GitHub did not answer. Try again in a moment.", "unreachable")
    owner = repo.split("/")[0]
    link = app_access_url(cloud)
    if _restricted(r):
        raise Refusal(422, _restricted_text(owner, repo, certain=True), "org_restricted", link)
    if not user.reads_private:
        raise Refusal(
            422,
            f"GitHub shows Canon no public repository called {repo}. If it is private or belongs to an organisation, "
            "connect private and organisation repositories first.",
            "connect",
        )
    org = _get(cloud, f"/orgs/{owner}", user.token)
    if org.status_code == 200 or _restricted(org):
        membership = _get(cloud, f"/user/memberships/orgs/{owner}", user.token)
        certain = _restricted(org) or _restricted(membership)
        raise Refusal(422, _restricted_text(owner, repo, certain=certain), "org_restricted", link)
    raise Refusal(422, f"GitHub has no repository called {repo} that your account can read.", "missing")


def _restricted_text(owner: str, repo: str, *, certain: bool) -> str:
    if certain:
        return (
            f"The {owner} organisation limits which OAuth apps can read its repositories, so GitHub will not show "
            f"{repo} to Canon. An owner of {owner} can approve Canon, and you can ask them to on GitHub."
        )
    return (
        f"GitHub did not show {repo} to Canon. If you can open it on GitHub, the {owner} organisation probably "
        f"limits which OAuth apps can read its repositories. An owner of {owner} can approve Canon, and you can ask "
        "them to on GitHub."
    )


def reader_token(cloud, slug: str, repo: str, user, *, private: bool) -> str | None:
    """A token that can still read the workspace's repository: the user's own first, then the owner's, then the
    other members' in the order they joined. Each is tried with one request.

    For a public repository any token will do, and None (no token) does too. For a private one, a Refusal when no
    member can read it any more."""
    secret = cloud.config.secret
    candidates = [user.token] + [unseal(sealed, secret) for uid, sealed in cloud.accounts().member_tokens(slug) if uid != user.id]
    for token in dict.fromkeys(t for t in candidates if t):
        if _get(cloud, f"/repos/{repo}", token).status_code == 200:
            return token
    if not private:
        return user.token
    owner = repo.split("/")[0]
    raise Refusal(
        409,
        f"No member of this workspace can read {repo} on GitHub any more. A member with access can sign in again, "
        f"or, if {owner} limits which OAuth apps can read its repositories, ask an owner of {owner} to approve Canon.",
        "no_reader",
        app_access_url(cloud),
    )


def github_user(cloud, login: str, token: str | None) -> dict | None:
    """GitHub's account for a handle ({id, login}), or None when there is none."""
    r = _get(cloud, f"/users/{login}", token)
    if r.status_code == 404:
        return None
    if _rate_limited(r):
        raise Refusal(429, "GitHub's rate limit was reached. Try again in a few minutes.", "rate_limit")
    if r.status_code != 200:
        raise Refusal(502, "GitHub did not answer. Try again in a moment.", "unreachable")
    body = r.json()
    if not isinstance(body, dict) or not isinstance(body.get("id"), int) or not body.get("login"):
        return None
    return {"id": body["id"], "login": str(body["login"]).lower(), "type": body.get("type")}
