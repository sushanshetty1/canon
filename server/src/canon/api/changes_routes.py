"""Catch me up.

- `GET /api/w/{ws}/changes?since=YYYY-MM-DD[&area=..&team=..]` returns typed changes (see `canon.changes`).
- `GET /api/w/{ws}/changes/brief?since=..[&area=..&team=..]` streams a checked brief of them as server-sent events,
  in the shape of Ask's events.
"""

import json
import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from canon.changes import brief, changes
from canon.config import settings

log = logging.getLogger("canon.api")
router = APIRouter()

DAY = r"^\d{4}-\d{2}-\d{2}$"
SLUG = r"^[a-z0-9][a-z0-9._-]{0,80}$|^PostHog\.com$"


def _since(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "since is a date: YYYY-MM-DD.") from None
    return value


@router.get("/api/w/{ws}/changes")
def changes_route(
    ws: str,
    request: Request,
    since: str = Query(pattern=DAY),
    area: str | None = Query(None, pattern=SLUG),
    team: str | None = Query(None, pattern=SLUG),
) -> dict:
    graph = request.app.state.workspace(ws)
    return changes(graph, _since(since), area=area, team=team)


@router.get("/api/w/{ws}/changes/brief")
def brief_route(
    ws: str,
    request: Request,
    since: str = Query(pattern=DAY),
    area: str | None = Query(None, pattern=SLUG),
    team: str | None = Query(None, pattern=SLUG),
) -> StreamingResponse:
    graph = request.app.state.workspace(ws)
    since = _since(since)
    run = getattr(request.app.state, "brief_fn", None)
    if run is None:
        if not settings().anthropic_api_key:
            raise HTTPException(503, "Briefs are off: no model key is set on the server.")
        run = brief

    async def events():
        try:
            async for event in run(graph, since, area=area, team=team):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            log.exception("brief failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Canon could not finish this brief. Try again.'})}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
