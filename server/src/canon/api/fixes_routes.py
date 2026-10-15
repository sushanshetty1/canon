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
from canon.fixes.queue import file_copy
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


def _role(request: Request, ws: str, user) -> str:
    """'public', 'owner' or 'member'. Writes need a signed-in user; on a private workspace, a member."""
    from canon.cloud.access import access

    if user is None:
        raise HTTPException(401, "Sign in with GitHub to file or dismiss fixes.")
    # The app-wide check has already worked out the role for this request.
    return getattr(request.state, "workspace_access", None) or access(request, ws)


@router.get("/api/w/{ws}/fixes")
def fixes_route(ws: str, request: Request, status: str = Query("open")) -> dict:
    if status not in FILTERS:
        raise HTTPException(422, f"status is one of {', '.join(FILTERS)}.")
    graph = _graph(request, ws)
    return {"fixes": list_fixes(graph, FILTERS[status]), "counts": totals(graph), "dry_run": dry_run()}


@router.post("/api/w/{ws}/fixes/{fix_id}/approve")
def approve_route(ws: str, fix_id: str, body: ApproveBody, request: Request, user=Depends(signed_in)) -> dict:
    graph = _graph(request, ws)
    role = _role(request, ws, user)
    try:
        # On a public workspace a visitor files the issue in their own repository; the shared queue stays as it is.
        if role == "public":
            return file_copy(graph, fix_id, repo=body.repo, user=user)
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
    if _role(request, ws, user) == "public":
        raise HTTPException(403, "Fixes on a public workspace stay in its queue. Create your own workspace to manage fixes.")
    try:
        return dismiss(graph, fix_id, reason=body.reason, user=user)
    except KeyError:
        raise HTTPException(404, "No such fix.") from None
    except TransitionError as e:
        raise HTTPException(409, str(e)) from None
