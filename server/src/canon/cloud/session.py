"""The signed session cookie, and who is signed in.

The cookie is `<user id>.<expiry unix>.<hex HMAC-SHA256>`. It holds no secrets, only who signed in and until when:
the signature stops anyone forging another user's id, and the expiry inside the signed text stops an old cookie
living longer than 30 days. It is HttpOnly and SameSite=Lax, so other sites cannot read it or send it with a
cross-site POST.

`current_user(request)` is how any route finds the signed-in user, with their GitHub token decrypted:

    from canon.cloud.session import current_user

    user = current_user(request)   # None when signed out
    user.login, user.token         # token is None for a development sign-in
"""

import hashlib
import hmac
import time
from dataclasses import dataclass, field

from fastapi import Request

from canon.cloud.crypto import derive, unseal

COOKIE = "canon_session"
MAX_AGE = 30 * 24 * 3600


@dataclass(frozen=True)
class User:
    id: str
    login: str
    name: str
    token: str | None = field(default=None, repr=False)  # the decrypted GitHub token; never logged
    dev: bool = False


def _mac(secret: str, user_id: str, expiry: int) -> str:
    return hmac.new(derive(secret, "session"), f"{user_id}.{expiry}".encode(), hashlib.sha256).hexdigest()


def sign(user_id: str, secret: str, now: float | None = None, max_age: int = MAX_AGE) -> str:
    if not secret:
        raise ValueError("A session needs a secret.")
    if not user_id or "." in user_id:
        raise ValueError("A user id must be non-empty and contain no dot.")
    expiry = int(time.time() if now is None else now) + max_age
    return f"{user_id}.{expiry}.{_mac(secret, user_id, expiry)}"


def verify(cookie: str | None, secret: str, now: float | None = None) -> str | None:
    """The user id the cookie was signed for, or None when it is missing, forged, malformed or expired."""
    if not cookie or not secret:
        return None
    parts = cookie.split(".")
    if len(parts) != 3:
        return None
    user_id, expiry_text, mac = parts
    if not user_id or not expiry_text.isdigit():
        return None
    expiry = int(expiry_text)
    if not hmac.compare_digest(mac.encode(), _mac(secret, user_id, expiry).encode()):
        return None
    if expiry <= (time.time() if now is None else now):
        return None
    return user_id


def cloud_of(request: Request):
    cloud = getattr(request.app.state, "cloud", None)
    if cloud is None:
        from canon.cloud import Cloud

        cloud = request.app.state.cloud = Cloud.from_env()
    return cloud


_UNSET = object()


def current_user(request: Request) -> User | None:
    """The signed-in user, or None. Looked up once per request."""
    cached = getattr(request.state, "canon_user", _UNSET)
    if cached is not _UNSET:
        return cached
    cloud = cloud_of(request)
    user = None
    if cloud.config.sessions:
        user_id = verify(request.cookies.get(COOKIE), cloud.config.secret, now=cloud.clock())
        row = cloud.accounts().user(user_id) if user_id else None
        if row:
            user = User(
                id=user_id,
                login=row["login"],
                name=row["name"] or row["login"],
                token=unseal(row["token"], cloud.config.secret),
                dev=bool(row["dev"]),
            )
    request.state.canon_user = user
    return user
