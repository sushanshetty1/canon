"""Who belongs to a workspace, and how an owner brings teammates in.

- `GET /api/w/{ws}/members` lists the members, owner first, and the open invites. Members only.
- `POST /api/w/{ws}/members {login}` invites a GitHub handle. Owner only. GitHub is asked for the account behind the
  handle, so the invite is tied to that account; the person becomes a member the next time they sign in or open
  their workspaces.
- `DELETE /api/w/{ws}/members/{login}` removes a member or cancels an invite. The owner can remove anyone but
  themselves; a member can remove themselves (leave).

Public workspaces have no members: these answer 403 there. A private workspace answers 404 to anyone outside it,
before any of these run (`canon.cloud.access`).
"""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from canon.cloud import repos
from canon.cloud.access import require_member
from canon.cloud.accounts import LimitReached
from canon.cloud.session import cloud_of

router = APIRouter()

_HANDLE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


class InviteBody(BaseModel):
    login: str = Field(min_length=1, max_length=60)


def _handle(text: str) -> str | None:
    """A GitHub handle from what a person types: `octocat`, `@octocat` or a github.com profile link."""
    t = re.sub(r"^(https?://)?(www\.)?github\.com/", "", (text or "").strip(), flags=re.I).strip("/@ ")
    return t.lower() if _HANDLE.match(t) else None


def _listing(cloud, ws: str, user) -> dict:
    accounts = cloud.accounts()
    role = accounts.role(user.id, ws)
    workspace = accounts.workspace(ws) or {}
    return {
        "role": role,
        "private": bool(workspace.get("private")),
        "repo": workspace.get("repo"),
        "members": [
            {"login": m["login"], "name": m["name"], "role": m["role"], "you": m["id"] == user.id} for m in accounts.members(ws)
        ],
        "invites": [{"login": i["login"], "at": i["at"]} for i in accounts.invites(ws)] if role == "owner" else [],
    }


@router.get("/api/w/{ws}/members")
def members(request: Request, ws: str) -> dict:
    user = require_member(request, ws)
    return _listing(cloud_of(request), ws, user)


@router.post("/api/w/{ws}/members")
def invite(request: Request, ws: str, body: InviteBody):
    cloud = cloud_of(request)
    user = require_member(request, ws)
    accounts = cloud.accounts()
    if accounts.role(user.id, ws) != "owner":
        raise HTTPException(403, "Only the workspace's owner can invite people.")
    login = _handle(body.login)
    if login is None:
        raise HTTPException(422, "Give a GitHub handle, like octocat.")
    try:
        account = repos.github_user(cloud, login, user.token)
    except repos.Refusal as e:
        if not user.dev:
            return e.response()
        account = {"id": None, "login": login, "type": "User"}  # development, offline: by handle only
    if account is None:
        raise HTTPException(422, f"GitHub has no account called {login}.")
    if account.get("type") == "Organization":
        raise HTTPException(422, f"{account['login']} is an organisation. Invite the people in it by their own handles.")
    try:
        status = accounts.invite(ws, account["login"], account["id"], by=user.login)
    except LimitReached as e:
        raise HTTPException(409, str(e)) from None
    return {"status": status, "login": account["login"], **_listing(cloud, ws, user)}


@router.delete("/api/w/{ws}/members/{login}")
def remove(request: Request, ws: str, login: str):
    cloud = cloud_of(request)
    user = require_member(request, ws)
    accounts = cloud.accounts()
    login = login.lower()
    owner = accounts.role(user.id, ws) == "owner"
    if login == user.login and owner:
        raise HTTPException(409, "The owner stays with the workspace.")
    if login != user.login and not owner:
        raise HTTPException(403, "Only the workspace's owner can remove people.")
    if not accounts.remove(ws, login):
        raise HTTPException(404, f"{login} is not a member of this workspace.")
    if login == user.login:
        return {"left": True}
    return _listing(cloud, ws, user)
