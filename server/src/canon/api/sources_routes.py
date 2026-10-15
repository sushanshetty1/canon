"""What a workspace reads, and exports uploaded into it.

- `GET /api/w/{ws}/sources` counts each kind of source (docs, tickets, chats, decisions, code owners, people): its
  documents, passages and facts, and when it was last read (`canon.sources.summary`). `can_upload` says whether the
  visitor may add an export.
- `POST /api/w/{ws}/uploads` takes one zip as multipart form data: `kind` is `slack` (a Slack export) or `pages` (a
  Notion or Confluence export), `file` is the zip. It needs a member of the workspace, a `Content-Length`, and at
  most 50 MB. The zip is read as a job, with the same progress as a sync (`GET /api/w/{ws}/jobs/latest`); one job
  runs per workspace at a time.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from canon.cloud.access import require_member
from canon.cloud.session import cloud_of
from canon.sources.summary import summary
from canon.sources.uploads import KINDS, MAX_UPLOAD

router = APIRouter()

FORM_SLACK = 64 * 1024  # room for the form's own fields and boundaries around the file


@router.get("/api/w/{ws}/sources")
def sources_route(ws: str, request: Request) -> dict:
    graph = request.app.state.workspace(ws)
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


@router.post("/api/w/{ws}/uploads")
async def upload_route(ws: str, request: Request):
    user = require_member(request, ws)  # before a byte of the body is read
    length = request.headers.get("content-length")
    if not length or not length.isdigit():
        raise HTTPException(411, "Send the export with its length.")
    if int(length) > MAX_UPLOAD + FORM_SLACK:
        raise HTTPException(413, "The export is larger than 50 MB.")
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
        raise HTTPException(413, "The export is larger than 50 MB.")
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
