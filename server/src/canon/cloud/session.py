"""Who is signed in. A stand-in until GitHub sign-in lands (Phase 2, Track D), which replaces this module.

The interface the rest of Canon relies on is only `current_user(request) -> User | None`, where a user has a
`login` (their GitHub handle) and a `token` (their GitHub token, used to file issues). With `CANON_DEV_LOGIN=1`
everyone is the development user; otherwise nobody is signed in.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    login: str
    token: str = ""
    name: str | None = None


def current_user(request) -> User | None:
    if os.environ.get("CANON_DEV_LOGIN") != "1":
        return None
    return User(login=os.environ.get("CANON_DEV_USER", "dev"), token=os.environ.get("CANON_DEV_GITHUB_TOKEN", ""))
