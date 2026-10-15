"""The fix queue over HTTP.

- `GET /api/w/{ws}/fixes?status=open|filed|dismissed|resolved|all` lists fixes, with counts per status.
- `POST /api/w/{ws}/fixes/{id}/approve {repo}` files the issue (or records it, in dry run) and returns the fix.
- `POST /api/w/{ws}/fixes/{id}/dismiss {reason}` dismisses it and returns the fix.

Reading is open to anyone who can read the workspace. Writing needs a signed-in member.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from canon.cloud import session
from canon.fixes import STATUSES, TransitionError, approve, dismiss, list_fixes, totals
from canon.fixes.issues import FilingError, dry_run

router = APIRouter()

FILTERS = {"open": ("open", "approved"), "filed": ("filed",), "dismissed": ("dismissed",), "resolved": ("resolved",), "all": STATUSES}


class ApproveBody(BaseModel):
    repo: str = Field(min_length=3, max_length=140)


class DismissBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def signed_in(request: Request):
    """The signed-in user, or None. Its own function so tests can stand in a user."""
    return session.current_user(request)


def _graph(request: Request, ws: str):
    return request.app.state.workspace(ws)


def _member(ws: str, user):
    if user is None:
        raise HTTPException(401, "Sign in to approve or dismiss fixes.")
    is_member = getattr(session, "is_member", None)
    if is_member is not None and not is_member(user, ws):
        raise HTTPException(403, "Only members of this workspace can approve or dismiss its fixes.")


@router.get("/api/w/{ws}/fixes")
def fixes_route(ws: str, request: Request, status: str = Query("open")) -> dict:
    if status not in FILTERS:
        raise HTTPException(422, f"status is one of {', '.join(FILTERS)}.")
    graph = _graph(request, ws)
    return {"fixes": list_fixes(graph, FILTERS[status]), "counts": totals(graph), "dry_run": dry_run()}


@router.post("/api/w/{ws}/fixes/{fix_id}/approve")
def approve_route(ws: str, fix_id: str, body: ApproveBody, request: Request, user=Depends(signed_in)) -> dict:
    graph = _graph(request, ws)
    _member(ws, user)
    try:
        return approve(graph, fix_id, repo=body.repo, user=user)
    except KeyError:
        raise HTTPException(404, "No such fix.") from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except TransitionError as e:
        raise HTTPException(409, str(e)) from None
    except FilingError as e:
        raise HTTPException(502, str(e)) from None


@router.post("/api/w/{ws}/fixes/{fix_id}/dismiss")
def dismiss_route(ws: str, fix_id: str, body: DismissBody, request: Request, user=Depends(signed_in)) -> dict:
    graph = _graph(request, ws)
    _member(ws, user)
    try:
        return dismiss(graph, fix_id, reason=body.reason, user=user)
    except KeyError:
        raise HTTPException(404, "No such fix.") from None
    except TransitionError as e:
        raise HTTPException(409, str(e)) from None
