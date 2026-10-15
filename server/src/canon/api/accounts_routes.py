"""Sign-in, the signed-in user, workspaces, and the jobs that fill them.

- `GET /auth/github?next=/app` sends the browser to GitHub with a random state, also kept in a short-lived cookie.
- `GET /auth/callback` checks the two match (so another site cannot finish a sign-in for you), trades the code for
  a token, reads the profile, stores the user with the token sealed, and sets the session cookie.
- `POST /auth/logout` clears the session.
- `GET /auth/dev-login?login=dev&next=/app` signs in without GitHub, only with `CANON_DEV_LOGIN=1` outside prod.
- `GET /api/me` is the signed-in user (or null) and which ways to sign in this server offers.
- `GET /api/workspaces` lists the public workspaces and the user's own; `POST /api/workspaces {repo}` makes one from
  a public GitHub repository and starts reading it.
- `POST /api/w/{ws}/sync` reads what changed since the last run; `GET /api/w/{ws}/jobs/latest` is the last job.
"""

import hmac
import logging
import secrets
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from canon.cloud import crypto, session
from canon.cloud.access import require_member, require_user
from canon.cloud.accounts import LimitReached
from canon.cloud.session import cloud_of, current_user

log = logging.getLogger("canon.auth")
router = APIRouter()

STATE_COOKIE = "canon_oauth_state"
STATE_MAX_AGE = 600
DEFAULT_NEXT = "/app"
SCOPE = "read:user public_repo"
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


def _failed(next_path: str) -> RedirectResponse:
    sep = "&" if "?" in next_path else "?"
    return RedirectResponse(f"{next_path}{sep}signin=failed", status_code=302)


# ----- sign-in ---------------------------------------------------------------------------------------------------


@router.get("/auth/github")
def github_login(request: Request, next: str | None = None):
    cloud = cloud_of(request)
    if not cloud.config.signin:
        return JSONResponse(status_code=503, content={"detail": "GitHub sign-in is not set up on this server."})
    state = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": cloud.config.github_client_id,
        "redirect_uri": f"{_base(cloud, request)}/auth/callback",
        "scope": SCOPE,
        "state": state,
        "allow_signup": "true",
    })
    resp = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)
    # The return path rides along in the state cookie; it is checked again on the way back.
    resp.set_cookie(
        STATE_COOKIE, f"{state}.{quote(safe_next(next), safe='')}", max_age=STATE_MAX_AGE, httponly=True,
        secure=_secure(cloud, request), samesite="lax", path="/",
    )
    return resp


def _github_token_and_profile(cloud, request: Request, code: str) -> tuple[str, dict] | None:
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
            token = r.json().get("access_token") if r.status_code == 200 else None
            if not token:
                log.warning("canon: GitHub token exchange failed (%s)", r.status_code)
                return None
            r = client.get(f"{API}/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            profile = r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning("canon: GitHub unreachable during sign-in (%s)", type(e).__name__)
        return None
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), int) or not profile.get("login"):
        return None
    return token, profile


@router.get("/auth/callback")
def github_callback(request: Request, code: str = "", state: str = ""):
    cloud = cloud_of(request)
    if not cloud.config.signin:
        return JSONResponse(status_code=503, content={"detail": "GitHub sign-in is not set up on this server."})
    stored = request.cookies.get(STATE_COOKIE) or ""
    expected, _, encoded_next = stored.partition(".")
    next_path = safe_next(unquote(encoded_next))
    if not expected or not state or not hmac.compare_digest(expected.encode(), state.encode()):
        return JSONResponse(status_code=400, content={"detail": "The sign-in state does not match. Sign in again."})
    got = _github_token_and_profile(cloud, request, code) if code else None
    if got is None:
        resp = _failed(next_path)
        resp.delete_cookie(STATE_COOKIE, path="/")
        return resp
    token, profile = got
    user_id = cloud.accounts().upsert_github_user(profile, crypto.seal(token, cloud.config.secret))
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
        "user": {"login": user.login, "name": user.name, "dev": user.dev} if user else None,
        "signin": cloud.config.signin,
        "dev_login": cloud.config.dev_login and cloud.config.sessions,
    }


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
    view = {k: w[k] for k in ("slug", "name", "repo", "public", "role")}
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
    own = [_workspace_view(cloud, w, with_job=True) for w in accounts.workspaces_of(user.id)] if user else []
    return {"public": public, "own": own}


def _check_repo(cloud, repo: str, token: str | None) -> dict:
    """The repository's API record when it exists and is public; else a 422 saying why."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "canon"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with cloud.http() as client:
            r = client.get(f"{API}/repos/{repo}", headers=headers)
    except Exception:
        raise HTTPException(502, "GitHub could not be reached. Try again in a moment.") from None
    if r.status_code == 404:
        raise HTTPException(422, f"GitHub has no public repository called {repo}.")
    if r.status_code != 200:
        raise HTTPException(502, "GitHub did not answer. Try again in a moment.")
    body = r.json()
    if body.get("private"):
        raise HTTPException(422, "Canon reads public repositories only.")
    return body


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


@router.post("/api/workspaces")
def create_workspace(request: Request, body: NewWorkspace):
    from canon.sources.repo import parse_repo

    cloud = cloud_of(request)
    user = require_user(request)
    repo = parse_repo(body.repo)
    if repo is None:
        raise HTTPException(422, "Give a repository as owner/name, like cli/cli.")
    meta = _check_repo(cloud, repo, user.token)
    repo = meta.get("full_name") or repo  # GitHub's own spelling
    try:
        workspace, created = cloud.accounts().create_workspace(user.id, repo)
    except LimitReached as e:
        raise HTTPException(409, str(e)) from None
    job = _start(cloud, workspace["slug"], repo, "create", user.token) if created else cloud.jobs().latest(workspace["slug"])
    return JSONResponse(
        status_code=201 if created else 200,
        content={"workspace": _workspace_view(cloud, workspace, with_job=False), "job": job, "created": created},
    )


@router.post("/api/w/{ws}/sync")
def sync(request: Request, ws: str):
    cloud = cloud_of(request)
    user = require_member(request, ws)
    workspace = cloud.accounts().workspace(ws)
    if not workspace or not workspace["repo"]:
        raise HTTPException(409, "This workspace has no repository to sync.")
    job = _start(cloud, ws, workspace["repo"], "sync", user.token)
    if job is None:
        raise HTTPException(409, "A sync is already running.")
    return {"job": job}


@router.get("/api/w/{ws}/jobs/latest")
def latest_job(request: Request, ws: str) -> dict:
    return {"job": cloud_of(request).jobs().latest(ws)}
