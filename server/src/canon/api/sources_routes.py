"""What a workspace reads, and exports uploaded into it.

- `GET /api/w/{ws}/sources` counts each kind of source (docs, tickets, chats, decisions, code owners, people): its
  documents, passages and facts, and when it was last read (`canon.sources.summary`). `can_upload` says whether the
  visitor may add an export.
- `POST /api/w/{ws}/uploads` takes one zip as multipart form data: `kind` is `slack` (a Slack export) or `pages` (a
  Notion or Confluence export), `file` is the zip. It needs a member of the workspace, a `Content-Length`, and at
  most 50 MB. The zip is read as a job, with the same progress as a sync (`GET /api/w/{ws}/jobs/latest`); one job
  runs per workspace at a time.
- `POST /api/w/{ws}/files` takes documents as multipart form data: `files` (Markdown, text, HTML, PDF, Word, or zips
  of them) and an optional `modified`, a JSON list of each file's last-modified time in milliseconds. They are read
  into the workspace's one Files connection (`canon.sources.upload`), the same way.

Both uploads share one set of limits and one zip reader (`canon.sources.archive`), and both run through the shared
pipeline (`canon.ingest.ingest_connector`).
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from canon.cloud.access import require_member
from canon.cloud.session import cloud_of
from canon.sources.summary import summary
from canon.sources.archive import MAX_UPLOAD
from canon.sources.uploads import KINDS

router = APIRouter()

FORM_SLACK = 64 * 1024  # room for the form's own fields and boundaries around the file


@router.get("/api/w/{ws}/sources")
def sources_route(ws: str, request: Request) -> dict:
    try:
        graph = request.app.state.workspace(ws)
    except HTTPException:
        # A workspace of your own with nothing read yet (one made to connect tools to) has sources to add, not a 404.
        if getattr(request.state, "workspace_access", "public") == "public":
            raise
        graph = cloud_of(request).graph(ws)
    view = summary(graph)
    view["can_upload"] = getattr(request.state, "workspace_access", "public") != "public"
    return view


def _real_upload(graph, kind: str, data: bytes, filename: str, by: str | None, report) -> dict:
    from canon.config import settings
    from canon.ingest import ingest_upload
    from canon.sources.cache import data_dir

    s = settings()
    check = None
    if s.anthropic_api_key:
        from canon.llm import check_model

        check = check_model()
    return ingest_upload(
        graph,
        kind,
        data,
        filename=filename,
        by=by,
        report=report,
        extract_model=s.extract_model if s.anthropic_api_key else None,
        extract_cache=data_dir() / "extract",
        check=check,
    )


def _sized(request: Request) -> None:
    """Every upload says how long it is, and is at most MAX_UPLOAD, before a byte of it is read."""
    length = request.headers.get("content-length")
    if not length or not length.isdigit():
        raise HTTPException(411, "Send the upload with its length.")
    if int(length) > MAX_UPLOAD + FORM_SLACK:
        raise HTTPException(413, "An upload can be at most 50 MB.")


@router.post("/api/w/{ws}/uploads")
async def upload_route(ws: str, request: Request):
    user = require_member(request, ws)  # before a byte of the body is read
    _sized(request)
    form = await request.form(max_files=1, max_fields=4)
    try:
        kind = str(form.get("kind") or "")
        file = form.get("file")
        if kind not in KINDS:
            raise HTTPException(422, "Upload a Slack export, or a Notion or Confluence export.")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, "Choose a zip file to upload.")
        data = await file.read(MAX_UPLOAD + 1)
        filename = (file.filename or "export.zip").rsplit("/", 1)[-1][:200]
    finally:
        await form.close()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "An upload can be at most 50 MB.")
    if not data.startswith(b"PK"):
        raise HTTPException(422, "This is not a zip file.")

    cloud = cloud_of(request)
    graph = cloud.graph(ws)
    run = cloud.upload or _real_upload
    by = user.login

    def start():
        return cloud.jobs().start(ws, "upload", lambda report: run(graph, kind, data, filename, by, report), step="unpack")

    job = await run_in_threadpool(start)
    if job is None:
        raise HTTPException(409, "Canon is already reading something into this workspace. Try again when it is done.")
    return JSONResponse(status_code=202, content={"job": job})


@router.post("/api/w/{ws}/files")
async def files_route(ws: str, request: Request):
    import json
    import time

    from canon.sources.client import SourceError
    from canon.sources.connections import UPLOAD_ID, Connections, start_sync
    from canon.sources.upload import MAX_FILES, File, UploadConnector

    user = require_member(request, ws)
    _sized(request)
    try:
        form = await request.form(max_files=MAX_FILES, max_fields=10)
    except Exception:
        raise HTTPException(422, f"Send at most {MAX_FILES} files as a form upload.") from None
    try:
        uploads = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
        if not uploads:
            raise HTTPException(422, "Choose at least one file.")
        try:
            modified = json.loads(str(form.get("modified") or "[]"))
        except ValueError:
            modified = []
        files: list[File] = []
        total = 0
        for i, f in enumerate(uploads):
            data = await f.read(MAX_UPLOAD + 1)
            total += len(data)
            if total > MAX_UPLOAD:
                raise HTTPException(413, "An upload can be at most 50 MB.")
            stamp = modified[i] if i < len(modified) and isinstance(modified[i], int | float) else None
            when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp / 1000)) if stamp and stamp > 0 else None
            files.append(File(f.filename or f"file-{i + 1}", data, when))
    finally:
        await form.close()

    cloud = cloud_of(request)

    def start():
        store = Connections(cloud.graph(ws))
        if store.get(UPLOAD_ID) is None:
            store.create("upload", "Files", {}, None, {}, user.login, conn_id=UPLOAD_ID)
        return start_sync(cloud, ws, UPLOAD_ID, connector=UploadConnector(files)), store.get(UPLOAD_ID)

    try:
        job, connection = await run_in_threadpool(start)
    except SourceError as e:
        raise HTTPException(422, e.public_message) from None
    if job is None:
        raise HTTPException(409, "Canon is already reading something into this workspace. Try again when it is done.")
    return JSONResponse(status_code=202, content={"job": job, "connection": connection})
