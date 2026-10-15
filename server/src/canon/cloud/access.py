"""Who may read and write a workspace.

`workspace_access` is a dependency on the whole app, so every route with a `{ws}` path parameter is checked before
it runs, including routes other modules add later:

- a public workspace (`posthog`, `demo`) is readable by anyone;
- a private workspace is readable only by its members. Signed out, it answers 401; signed in as someone else, it
  answers 404, the same as a workspace that does not exist;
- anything not in the accounts graph is a 404.

Routes that change a workspace call `require_member(request, ws)`: public workspaces are read-only to everyone.
"""

from fastapi import HTTPException, Request

from canon.cloud.session import User, cloud_of, current_user

NOT_FOUND = "No such workspace."
SIGN_IN = "Sign in to open this workspace."
READ_ONLY = "This workspace is read-only."


def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


def access(request: Request, ws: str) -> str:
    """'public' or the member's role ('owner' or 'member'). Raises 401 or 404 when the request may not read."""
    cloud = cloud_of(request)
    if ws in cloud.config.public_workspaces:
        return "public"
    try:
        workspace = cloud.accounts().workspace(ws)
    except ValueError:
        workspace = None
    if workspace is None:
        raise HTTPException(404, NOT_FOUND)
    if workspace["public"]:
        return "public"
    user = current_user(request)
    if user is None:
        raise HTTPException(401, SIGN_IN)
    role = cloud.accounts().role(user.id, ws)
    if role is None:
        raise HTTPException(404, NOT_FOUND)
    return role


def workspace_access(request: Request) -> None:
    """The app-wide check: runs for every route whose path has `{ws}`."""
    ws = request.path_params.get("ws")
    if ws is not None:
        request.state.workspace_access = access(request, ws)


def require_member(request: Request, ws: str) -> User:
    """The signed-in member of `ws`, for routes that change it. 401 signed out, 403 on a public workspace, 404 for a
    workspace the user cannot see."""
    role = access(request, ws)
    user = require_user(request)
    if role == "public":
        raise HTTPException(403, READ_ONLY)
    return user
