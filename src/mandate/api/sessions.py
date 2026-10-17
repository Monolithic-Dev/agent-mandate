"""Console sign-in: password hashes and server-side sessions.

Passwords are hashed with scrypt (standard library, memory-hard) and a random salt per user.
Signing in creates a Session in the graph and gives the browser a random token in an
HttpOnly, SameSite=Strict cookie; only the token's SHA-256 is stored, so a copy of the
database cannot be replayed as a cookie. Each request looks the session up, so signing out,
"sign out everywhere", a password change or reset, and disabling the user all end sessions at
once, on the server. A session ends after ``MANDATE_SESSION_TTL_SECONDS`` at the latest, or
sooner after ``MANDATE_SESSION_IDLE_SECONDS`` without a request.

A request that changes something with a cookie must also carry ``X-Mandate-Client: console``:
another site cannot add that header without a CORS preflight this API never grants, so a
forged cross-site form or fetch is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

SESSION_COOKIE = "mandate_session"
CLIENT_HEADER = "X-Mandate-Client"
CLIENT_VALUE = "console"

# scrypt cost: 2^15 iterations, 8 blocks, 1 lane uses 32 MiB and roughly 50-100 ms per hash.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
KEY_BYTES = 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, n: int | None = None) -> str:
    n = n or SCRYPT_N
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=n,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=KEY_BYTES,
    )
    return f"scrypt${n}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check. A malformed hash never matches."""
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=SCRYPT_MAXMEM,
            dklen=KEY_BYTES,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, _unb64(expected))


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """Checked against when no user has the email, so a miss takes as long as a wrong password."""
    return hash_password(secrets.token_urlsafe(16))


TOKEN_PREFIX = "mst_"
# A session's last-seen time is written at most this often, not on every request.
TOUCH_EVERY_MS = 60_000


def new_session_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_token(token: str) -> bool:
    """Cheap shape check, so garbage never costs a database read."""
    return token.startswith(TOKEN_PREFIX) and 40 <= len(token) <= 64
