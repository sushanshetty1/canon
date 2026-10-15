"""Decisions: `GET /api/w/{ws}/decisions` and `GET /api/w/{ws}/decisions/{id}` (see `canon.decisions.read`)."""

from datetime import date

from fastapi import APIRouter, HTTPException, Request

from canon.decisions import read

router = APIRouter()


@router.get("/api/w/{ws}/decisions")
def decisions_route(ws: str, request: Request) -> dict:
    items = read.decisions(request.app.state.workspace(ws))
    counts: dict[str, int] = {}
    for d in items:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    return {"today": date.today().isoformat(), "counts": counts, "decisions": items}


@router.get("/api/w/{ws}/decisions/{decision_id}")
def decision_route(ws: str, decision_id: str, request: Request) -> dict:
    found = read.decision(request.app.state.workspace(ws), decision_id)
    if found is None:
        raise HTTPException(404, "No such decision.")
    return found
