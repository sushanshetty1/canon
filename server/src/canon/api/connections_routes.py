"""Connections: the tools a workspace reads, and the files people upload to it.

- `GET /api/w/{ws}/connections` lists the workspace's connections with their last sync, counts, notes and errors.
  Never a secret.
- `POST /api/w/{ws}/connections {kind, label, config, secret}` checks the credential with one cheap call (Slack
  `auth.test`, Notion `users/me`, Linear `viewer`, Jira `myself`, Confluence `user/current`), answers 422 with
  what is wrong when it fails, else stores it sealed and starts the first sync.
- `POST /api/w/{ws}/connections/{id}/sync` syncs one connection now, as the workspace's job.
- `DELETE /api/w/{ws}/connections/{id}?documents=keep|delete` removes a connection. Its documents stay, marked
  removed (their facts are closed, not lost), or are deleted with their passages and facts.
- `POST /api/w/{ws}/files` (multipart, `files` and optional `modified`, a JSON list of millisecond times) reads
  uploaded files into the workspace.
- `POST /api/workspaces/blank {name}` makes an empty workspace to connect sources to, for a company without a
  repository to start from.

Every write needs a member of the workspace (`require_member`); public workspaces cannot be connected to anything.
"""

import json
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from canon.cloud import crypto
from canon.cloud.access import require_member, require_user
from canon.cloud.session import cloud_of
from canon.sources.client import SourceError
from canon.sources.connections import (
    API_KINDS,
    KINDS,
    MAX_CONNECTIONS,
    UPLOAD_ID,
    Connections,
    check,
    clean_config,
    remove_documents,
    secret_of,
    start_sync,
)

log = logging.getLogger("canon.connections")
router = APIRouter()


class NewConnection(BaseModel):
    kind: str = Field(max_length=20)
    label: str | None = Field(default=None, max_length=80)
    config: dict = Field(default_factory=dict)
    secret: str = Field(default="", max_length=4000)


class BlankWorkspace(BaseModel):
    name: str = Field(min_length=2, max_length=60)


def _graph_exists(cloud, ws: str) -> bool:
    from canon.graph.db import workspace_graph_name

    return workspace_graph_name(ws) in cloud.db().list_graphs()


def _store(cloud, ws: str) -> Connections:
    return Connections(cloud.graph(ws))


def _failed(e: SourceError) -> HTTPException:
    unreachable = "could not be reached" in e.public_message or "did not answer" in e.public_message
    return HTTPException(502 if unreachable else 422, e.public_message)


@router.get("/api/w/{ws}/connections")
def list_connections(request: Request, ws: str) -> dict:
    cloud = cloud_of(request)
    if request.state.workspace_access == "public" or not _graph_exists(cloud, ws):
        return {"connections": [], "job": None, "can_connect": request.state.workspace_access != "public"}
    return {"connections": _store(cloud, ws).list(), "job": cloud.jobs().latest(ws), "can_connect": True}


@router.post("/api/w/{ws}/connections")
def create_connection(request: Request, ws: str, body: NewConnection):
    cloud = cloud_of(request)
    user = require_member(request, ws)
    kind = body.kind.strip().lower()
    if kind not in API_KINDS:
        raise HTTPException(422, "Canon connects to Slack, Notion, Linear, Jira and Confluence. Upload files instead.")
    store = _store(cloud, ws)
    if store.count() >= MAX_CONNECTIONS:
        raise HTTPException(409, f"A workspace can have at most {MAX_CONNECTIONS} connections.")
    config = clean_config(kind, body.config)
    try:
        secret = secret_of(kind, body.config, body.secret)
        info = check(kind, config, secret, http=cloud.http, sleep=getattr(cloud, "sleep", time.sleep))
    except SourceError as e:
        raise _failed(e) from None
    if kind in ("jira", "confluence"):
        from canon.sources.atlassian import site_url

        config["site"] = site_url(config.get("site"))
    name = info.get("team") or info.get("workspace") or info.get("organization") or (config.get("site") or "").removeprefix("https://")
    label = (body.label or "").strip() or (f"{KINDS[kind]} · {name}" if name else KINDS[kind])
    conn = store.create(kind, label, config, crypto.seal(secret, cloud.config.secret), info, user.login,
                        conn_id=secrets.token_hex(6))
    job = start_sync(cloud, ws, conn["id"])
    return JSONResponse(status_code=201, content={"connection": store.get(conn["id"]), "job": job})


@router.post("/api/w/{ws}/connections/{conn_id}/sync")
def sync_connection(request: Request, ws: str, conn_id: str) -> dict:
    cloud = cloud_of(request)
    require_member(request, ws)
    store = _store(cloud, ws)
    conn = store.get(conn_id) if _graph_exists(cloud, ws) else None
    if conn is None:
        raise HTTPException(404, "No such connection.")
    if conn["kind"] not in API_KINDS:
        raise HTTPException(409, "Files are read when they are uploaded. Upload them again to read a new version.")
    try:
        job = start_sync(cloud, ws, conn_id)
    except SourceError as e:
        raise _failed(e) from None
    if job is None:
        raise HTTPException(409, "A sync is already running in this workspace.")
    return {"job": job, "connection": store.get(conn_id)}


@router.delete("/api/w/{ws}/connections/{conn_id}")
def delete_connection(request: Request, ws: str, conn_id: str, documents: str = "keep") -> dict:
    cloud = cloud_of(request)
    require_member(request, ws)
    if documents not in ("keep", "delete"):
        raise HTTPException(422, "documents is keep or delete.")
    store = _store(cloud, ws)
    if not _graph_exists(cloud, ws) or store.get(conn_id) is None:
        raise HTTPException(404, "No such connection.")
    job = cloud.jobs().latest(ws)
    if job and job["status"] == "running":
        raise HTTPException(409, "A sync is running. Remove the connection when it finishes.")
    graph = cloud.graph(ws)
    count = remove_documents(graph, conn_id, delete=documents == "delete")
    store.delete(conn_id)
    return {"removed": conn_id, "documents": count, "kept": documents == "keep"}


# ----- uploads ---------------------------------------------------------------------------------------------------


@router.post("/api/w/{ws}/files")
async def upload_files(request: Request, ws: str):
    from canon.sources.upload import MAX_FILES, MAX_TOTAL, File, UploadConnector

    cloud = cloud_of(request)
    user = require_member(request, ws)
    length = request.headers.get("content-length")
    if not length or not length.isdigit():
        raise HTTPException(411, "Send the upload with its length.")
    if int(length) > MAX_TOTAL + 1024 * 1024:
        raise HTTPException(413, f"An upload can be at most {MAX_TOTAL // (1024 * 1024)} MB.")
    try:
        form = await request.form(max_files=MAX_FILES, max_fields=10)
    except Exception:
        raise HTTPException(422, f"Send at most {MAX_FILES} files as a form upload.") from None
    uploads = [f for f in form.getlist("files") if hasattr(f, "read")]
    if not uploads:
        raise HTTPException(422, "Choose at least one file.")
    try:
        modified = json.loads(str(form.get("modified") or "[]"))
    except ValueError:
        modified = []
    files: list[File] = []
    total = 0
    for i, f in enumerate(uploads):
        data = await f.read(MAX_TOTAL + 1)  # type: ignore[union-attr]
        total += len(data)
        if total > MAX_TOTAL:
            raise HTTPException(413, f"An upload can be at most {MAX_TOTAL // (1024 * 1024)} MB.")
        stamp = modified[i] if i < len(modified) and isinstance(modified[i], int | float) else None
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp / 1000)) if stamp and stamp > 0 else None
        files.append(File(getattr(f, "filename", None) or f"file-{i + 1}", data, when))
    await form.close()

    store = _store(cloud, ws)
    if store.get(UPLOAD_ID) is None:
        store.create("upload", "Files", {}, None, {}, user.login, conn_id=UPLOAD_ID)
    try:
        job = start_sync(cloud, ws, UPLOAD_ID, connector=UploadConnector(files))
    except SourceError as e:
        raise _failed(e) from None
    if job is None:
        raise HTTPException(409, "A sync is running in this workspace. Upload again when it finishes.")
    return JSONResponse(status_code=202, content={"job": job, "connection": store.get(UPLOAD_ID)})


# ----- a workspace with no repository ----------------------------------------------------------------------------


def create_blank_workspace(cloud, user_id: str, name: str) -> dict:
    """A new, empty workspace owned by the user, named `name`, to connect sources to."""
    from canon.cloud.accounts import MAX_WORKSPACES, RESERVED, LimitReached, slug_for
    from canon.graph.db import workspace_graph_name

    accounts = cloud.accounts()
    q = lambda c, p: accounts.graph.query(c, p).result_set  # noqa: E731
    owned = q("MATCH (:User {id: $user})-[m:MEMBER {role: 'owner'}]->(:Workspace) RETURN count(m)", {"user": user_id})
    if owned and owned[0][0] >= MAX_WORKSPACES:
        raise LimitReached(f"You have {MAX_WORKSPACES} workspaces, the most allowed.")
    base = slug_for(name)
    if base.startswith("test"):  # throwaway graphs are named test_..., so a workspace never is
        base = f"w-{base}"
    graphs = set(cloud.db().list_graphs())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cloud.clock()))
    for n in range(1, 50):
        slug = base if n == 1 else f"{base}-{n}"
        if slug in RESERVED or slug in cloud.config.public_workspaces or slug.startswith("test"):
            continue
        if workspace_graph_name(slug) in graphs:
            continue  # a graph that exists already belongs to something else
        claim = secrets.token_hex(8)
        rows = q(
            """MATCH (u:User {id: $user})
               MERGE (w:Workspace {slug: $slug})
               ON CREATE SET w.name = $name, w.repo = null, w.public = false, w.created_at = $now, w.claim = $claim
               WITH u, w WHERE w.claim = $claim
               MERGE (u)-[m:MEMBER]->(w) SET m.role = 'owner', m.at = $now
               RETURN w.slug""",
            {"user": user_id, "slug": slug, "name": name, "now": now, "claim": claim},
        )
        if rows:
            return accounts.workspaces_of_one(user_id, slug)
    raise LimitReached("No free name for this workspace.")


@router.post("/api/workspaces/blank")
def blank_workspace(request: Request, body: BlankWorkspace):
    from canon.cloud.accounts import LimitReached

    cloud = cloud_of(request)
    user = require_user(request)
    name = " ".join(body.name.split())
    try:
        workspace = create_blank_workspace(cloud, user.id, name)
    except LimitReached as e:
        raise HTTPException(409, str(e)) from None
    view = {k: workspace[k] for k in ("slug", "name", "repo", "public", "role")}
    return JSONResponse(status_code=201, content={"workspace": view})
