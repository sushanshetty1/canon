"""Sign-in, the signed-in user, workspaces, and the jobs that fill them.

- `GET /auth/github?next=/app` sends the browser to GitHub with a random state, also kept in a short-lived cookie.
  It asks for `read:user public_repo`: the profile, and public repositories (to file the issues a user approves).
- `GET /auth/github?access=private&next=/app/new` is the separate step that connects private and organisation
  repositories: the same flow, asking for `read:user repo read:org`. GitHub offers OAuth apps no read-only scope
  for private repositories, so `repo` it is; Canon only reads with it.
- `GET /auth/callback` checks the state matches the cookie (so another site cannot finish a sign-in for you), trades
  the code for a token, reads the profile, stores the user with the token sealed and the scopes GitHub granted
  (the token response's `scope`), and sets the session cookie.
- `POST /auth/logout` clears the session.
- `GET /auth/dev-login?login=dev&next=/app` signs in without GitHub, only with `CANON_DEV_LOGIN=1` outside prod.
- `GET /api/me` is the signed-in user (or null), whether their token reads private repositories, and which ways to
  sign in this server offers.
- `GET /api/github/repos?q=&owner=&page=` is a page of the user's repositories, grouped by owner, read from GitHub
  with the user's token on the server.
- `GET /api/workspaces` lists the public workspaces and the user's own; `POST /api/workspaces {repo}` makes one from
  a repository the user's token can read (public, private or an organisation's) and starts reading it. Asking again
  for a workspace the user already belongs to opens it.
- `POST /api/w/{ws}/sync` reads what changed since the last run, with the token of a member who can still read the
  repository; `GET /api/w/{ws}/jobs/latest` is the last job.
"""

import hmac
import logging
import secrets
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from canon.cloud import crypto, repos, session
from canon.cloud.access import require_member, require_user
from canon.cloud.accounts import LimitReached, reads_private
from canon.cloud.session import cloud_of, current_user

log = logging.getLogger("canon.auth")
router = APIRouter()

STATE_COOKIE = "canon_oauth_state"
STATE_MAX_AGE = 600
DEFAULT_NEXT = "/app"
SCOPE = "read:user public_repo"  # sign-in
PRIVATE_SCOPE = "read:user repo read:org"  # connect private and organisation repositories
MODES = {"signin": SCOPE, "private": PRIVATE_SCOPE}
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"


def safe_next(value: str | None) -> str:
    """A same-site path to return to after sign-in. Anything else (another host, //host, /\\host) becomes /app."""
    if not value or len(value) > 512 or not value.startswith("/") or value.startswith("//"):
        return DEFAULT_NEXT
    if "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return DEFAULT_NEXT
    return value


def _base(cloud, request: Request) -> str:
    return cloud.config.public_url or str(request.base_url).rstrip("/")


def _secure(cloud, request: Request) -> bool:
    return _base(cloud, request).startswith("https://")


def _set_session(cloud, request: Request, resp, user_id: str) -> None:
    resp.set_cookie(
        session.COOKIE, session.sign(user_id, cloud.config.secret, now=cloud.clock()), max_age=session.MAX_AGE,
        httponly=True, secure=_secure(cloud, request), samesite="lax", path="/",
    )


def _with(next_path: str, flag: str) -> str:
    return f"{next_path}{'&' if '?' in next_path else '?'}{flag}"


def _failed(next_path: str) -> RedirectResponse:
    return RedirectResponse(_with(next_path, "signin=failed"), status_code=302)


def _state_cookie(value: str) -> tuple[str, str, str]:
    """(state, mode, next path) from the state cookie `<state>.<mode>.<quoted next>`. A cookie set before modes
    existed is `<state>.<quoted next>`: a quoted path starts with `%2F`, never with a mode's name."""
    expected, _, rest = value.partition(".")
    mode, dot, encoded = rest.partition(".")
    if not dot or mode not in MODES:
        mode, encoded = "signin", rest
    return expected, mode, safe_next(unquote(encoded))


# ----- sign-in ---------------------------------------------------------------------------------------------------


@router.get("/auth/github")
def github_login(request: Request, next: str | None = None, access: str | None = None):
    """Sign in (`read:user public_repo`), or with `access=private` connect private and organisation repositories
    (`read:user repo read:org`)."""
    cloud = cloud_of(request)
    if not cloud.config.signin:
        return JSONResponse(status_code=503, content={"detail": "GitHub sign-in is not set up on this server."})
    mode = "private" if access == "private" else "signin"
    state = secrets.token_urlsafe(24)  # URL-safe base64: never contains the cookie's dots
    query = urlencode({
        "client_id": cloud.config.github_client_id,
        "redirect_uri": f"{_base(cloud, request)}/auth/callback",
        "scope": MODES[mode],
        "state": state,
        "allow_signup": "true",
    })
    resp = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)
    # The mode and the return path ride along in the state cookie; the path is checked again on the way back.
    resp.set_cookie(
        STATE_COOKIE, f"{state}.{mode}.{quote(safe_next(next), safe='')}", max_age=STATE_MAX_AGE, httponly=True,
        secure=_secure(cloud, request), samesite="lax", path="/",
    )
    return resp


def _github_token_and_profile(cloud, request: Request, code: str) -> tuple[str, dict, str] | None:
    """(token, profile, granted scopes) for an OAuth code, or None."""
    cfg = cloud.config
    try:
        with cloud.http() as client:
            r = client.post(
                TOKEN_URL,
                data={
                    "client_id": cfg.github_client_id,
                    "client_secret": cfg.github_client_secret,
                    "code": code,
                    "redirect_uri": f"{_base(cloud, request)}/auth/callback",
                },
                headers={"Accept": "application/json"},
            )
            body = r.json() if r.status_code == 200 else {}
            token = body.get("access_token") if isinstance(body, dict) else None
            if not token:
                log.warning("canon: GitHub token exchange failed (%s)", r.status_code)
                return None
            scopes = str(body.get("scope") or "")  # what the user granted, which can differ from what was asked
            r = client.get(f"{API}/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            profile = r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning("canon: GitHub unreachable during sign-in (%s)", type(e).__name__)
        return None
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), int) or not profile.get("login"):
        return None
    return token, profile, scopes


@router.get("/auth/callback")
def github_callback(request: Request, code: str = "", state: str = ""):
    cloud = cloud_of(request)
    if not cloud.config.signin:
        return JSONResponse(status_code=503, content={"detail": "GitHub sign-in is not set up on this server."})
    expected, mode, next_path = _state_cookie(request.cookies.get(STATE_COOKIE) or "")
    if not expected or not state or not hmac.compare_digest(expected.encode(), state.encode()):
        return JSONResponse(status_code=400, content={"detail": "The sign-in state does not match. Sign in again."})
    got = _github_token_and_profile(cloud, request, code) if code else None
    if got is None:
        resp = _failed(next_path)
        resp.delete_cookie(STATE_COOKIE, path="/")
        return resp
    token, profile, scopes = got
    user_id = cloud.accounts().upsert_github_user(profile, crypto.seal(token, cloud.config.secret), scopes)
    if mode == "private" and not reads_private(cloud.accounts().user(user_id)["scopes"]):
        next_path = _with(next_path, "connect=incomplete")  # the user unticked a scope on GitHub's page
    resp = RedirectResponse(next_path, status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    _set_session(cloud, request, resp, user_id)
    return resp


@router.get("/auth/dev-login")
def dev_login(request: Request, login: str = "dev", next: str | None = None):
    cloud = cloud_of(request)
    if not cloud.config.dev_login or cloud.config.profile == "prod" or not cloud.config.sessions:
        raise HTTPException(404, "Not found.")
    user_id = cloud.accounts().upsert_dev_user(login)
    resp = RedirectResponse(safe_next(next), status_code=302)
    _set_session(cloud, request, resp, user_id)
    return resp


@router.post("/auth/logout")
def logout(request: Request):
    cloud = cloud_of(request)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(session.COOKIE, path="/", httponly=True, secure=_secure(cloud, request), samesite="lax")
    return resp


@router.get("/api/me")
def me(request: Request) -> dict:
    cloud = cloud_of(request)
    user = current_user(request)
    return {
        "user": {"login": user.login, "name": user.name, "dev": user.dev, "private_repos": user.reads_private} if user else None,
        "signin": cloud.config.signin,
        "dev_login": cloud.config.dev_login and cloud.config.sessions,
        "app_access_url": repos.app_access_url(cloud) if cloud.config.signin else None,
    }


# ----- the user's repositories ------------------------------------------------------------------------------------


@router.get("/api/github/repos")
def github_repos(request: Request, q: str = "", owner: str = "", page: int = 1, refresh: bool = False):
    """A page of the signed-in user's repositories. GitHub is called here with the user's token; the browser only
    ever sees the list."""
    cloud = cloud_of(request)
    user = require_user(request)
    base = {"connected": bool(user.token), "private": user.reads_private, "login": user.login, "truncated": False}
    if not user.token:
        return {**base, **repos.repo_page([], user.login)}
    try:
        rows, truncated = repos.user_repos(cloud, user, refresh=refresh)
    except repos.Refusal as e:
        return e.response()
    return {**base, "truncated": truncated, **repos.repo_page(rows, user.login, q=q[:100], owner=owner[:40], page=page)}


# ----- workspaces ------------------------------------------------------------------------------------------------


class NewWorkspace(BaseModel):
    repo: str = Field(min_length=3, max_length=200)


def suggestions(graph) -> list[str]:
    """Questions this workspace's graph can answer, for the Ask screen: owners of its areas, then a topic."""
    out = []
    try:
        rows = graph.query(
            """MATCH (f:Fact {predicate: 'owned_by'})-[:ABOUT]->(a:Area)
               WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->() AND a.slug <> 'all'
               WITH DISTINCT coalesce(a.name, a.slug) AS name RETURN name ORDER BY size(name), name LIMIT 2"""
        ).result_set
        out += [f"Who owns {name}?" for (name,) in rows]
        rows = graph.query(
            """MATCH (f:Fact)-[:ABOUT]->(t:Topic) WHERE f.predicate IN ['process', 'policy'] AND f.valid_to IS NULL
               WITH coalesce(t.key, '') AS key, count(f) AS n WHERE key <> '' RETURN key ORDER BY n DESC, key LIMIT 1"""
        ).result_set
        out += [f"How does {key.removeprefix('topic:').replace('-', ' ')} work?" for (key,) in rows]
    except Exception:
        pass
    return out or ["Who owns the whole repository?", "How do I contribute?"]


def _workspace_view(cloud, w: dict, *, with_job: bool) -> dict:
    view = {k: w[k] for k in ("slug", "name", "repo", "public", "role", "private")}
    if with_job:
        graph = cloud.graph(w["slug"])
        view["job"] = cloud.jobs().latest(w["slug"])
        view["suggestions"] = suggestions(graph)
    return view


@router.get("/api/workspaces")
def list_workspaces(request: Request) -> dict:
    cloud = cloud_of(request)
    accounts = cloud.accounts()
    user = current_user(request)
    public = [_workspace_view(cloud, w, with_job=False) for w in accounts.public_workspaces()]
    if user:
        accounts.claim_invites(user.id)  # an invite made while they were signed in shows up without signing in again
    own = [_workspace_view(cloud, w, with_job=True) for w in accounts.workspaces_of(user.id)] if user else []
    return {"public": public, "own": own}


def _start(cloud, slug: str, repo: str, kind: str, token: str | None) -> dict | None:
    graph = cloud.graph(slug)
    ingest = cloud.ingest or _real_ingest
    return cloud.jobs().start(slug, kind, lambda report: ingest(graph, repo, token, report))


def _real_ingest(graph, repo: str, token: str | None, report) -> dict:
    from canon.config import settings
    from canon.ingest import ingest_repo
    from canon.sources.cache import data_dir
    from canon.sources.text import slugify

    s = settings()
    check = None
    if s.anthropic_api_key:
        from canon.llm import check_model

        check = check_model()
    return ingest_repo(
        graph,
        repo,
        cache_root=data_dir() / "raw" / "repos" / slugify(repo),
        token=token,
        report=report,
        extract_model=s.extract_model if s.anthropic_api_key else None,
        extract_cache=data_dir() / "extract",
        check=check,
    )


def _opened(cloud, workspace: dict, job, created: bool) -> JSONResponse:
    return JSONResponse(
        status_code=201 if created else 200,
        content={"workspace": _workspace_view(cloud, workspace, with_job=False), "job": job, "created": created},
    )


@router.post("/api/workspaces")
def create_workspace(request: Request, body: NewWorkspace):
    """Make a workspace from a repository the user's token can read, or open the one they already belong to."""
    from canon.sources.repo import parse_repo

    cloud = cloud_of(request)
    user = require_user(request)
    accounts = cloud.accounts()
    repo = parse_repo(body.repo)
    # A retry, a second click or the workspace's own slug opens the workspace the user already belongs to, before
    # GitHub is asked anything: GitHub's answer can change (a rate limit, a lapsed grant) but membership has not.
    existing = accounts.find_own(user.id, repo or body.repo)
    if existing:
        return _opened(cloud, existing, cloud.jobs().latest(existing["slug"]), False)
    if repo is None:
        raise HTTPException(422, "Give a repository as owner/name, like cli/cli.")
    try:
        meta = repos.check_repo(cloud, repo, user)
    except repos.Refusal as e:
        return e.response()
    repo = meta.get("full_name") or repo  # GitHub's own spelling
    try:
        workspace, created = accounts.create_workspace(user.id, repo, private=bool(meta.get("private")))
    except LimitReached as e:
        raise HTTPException(409, str(e)) from None
    job = _start(cloud, workspace["slug"], repo, "create", user.token) if created else cloud.jobs().latest(workspace["slug"])
    return _opened(cloud, workspace, job, created)


@router.post("/api/w/{ws}/sync")
def sync(request: Request, ws: str):
    cloud = cloud_of(request)
    user = require_member(request, ws)
    workspace = cloud.accounts().workspace(ws)
    if not workspace or not workspace["repo"]:
        raise HTTPException(409, "This workspace has no repository to sync.")
    try:
        token = repos.reader_token(cloud, ws, workspace["repo"], user, private=workspace["private"])
    except repos.Refusal as e:
        return e.response()
    job = _start(cloud, ws, workspace["repo"], "sync", token)
    if job is None:
        raise HTTPException(409, "A sync is already running.")
    return {"job": job}


@router.get("/api/w/{ws}/jobs/latest")
def latest_job(request: Request, ws: str) -> dict:
    return {"job": cloud_of(request).jobs().latest(ws)}
