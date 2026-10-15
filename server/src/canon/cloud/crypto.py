"""Keys derived from `CANON_SESSION_SECRET`, and GitHub tokens sealed at rest.

One secret gives two keys, each derived for its own purpose, so the key that signs cookies never encrypts tokens.
A token is sealed with AES-256-GCM under a fresh random nonce: `v1.<base64url(nonce + ciphertext + tag)>`. Opening
anything that was not sealed with this secret (a changed secret, a tampered value) gives None, never an error.
"""

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "v1."


def derive(secret: str, purpose: str) -> bytes:
    return hashlib.sha256(f"canon:{purpose}:".encode() + secret.encode()).digest()


def seal(token: str, secret: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(derive(secret, "tokens")).encrypt(nonce, token.encode(), b"github-token")
    return _PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def unseal(value: str | None, secret: str) -> str | None:
    if not value or not value.startswith(_PREFIX) or not secret:
        return None
    try:
        raw = base64.urlsafe_b64decode(value[len(_PREFIX) :].encode())
        return AESGCM(derive(secret, "tokens")).decrypt(raw[:12], raw[12:], b"github-token").decode()
    except (InvalidTag, ValueError):
        return None
