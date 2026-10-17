"""Authentication and rate limiting for the REST API.

A request authenticates with an API key (``X-Mandate-Key``) or, from the console, with a
signed session cookie (``mandate.api.sessions``). A key, when sent, always wins.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Callable

from fastapi import Request

from mandate.api.keys import (
    SELF_SERVICE_PREFIX,
    Caller,
    Role,
    find_key,
    key_caller,
    required_role,
)
from mandate.api.sessions import (
    CLIENT_HEADER,
    CLIENT_VALUE,
    SESSION_COOKIE,
    TOUCH_EVERY_MS,
    looks_like_token,
    token_hash,
)
from mandate.errors import Forbidden, NotFound, RateLimited, Unauthorized

API_KEY_HEADER = "X-Mandate-Key"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RateLimiter:
    """A token bucket per key: ``limit_per_minute`` requests per minute, refilled smoothly."""

    def __init__(
        self, limit_per_minute: int, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._capacity = float(limit_per_minute)
        self._rate = limit_per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


def check_api_key(provided: str | None, expected: str) -> None:
    """Constant-time comparison; raises ``Unauthorized`` for a missing or wrong key."""
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise Unauthorized("missing or invalid API key")


def session_caller(request: Request, token: str) -> Caller | None:
    """The signed-in user a session cookie names, or None if the session is no longer good.
    Sets ``request.state.session_id`` for the routes that manage sessions."""
    if not looks_like_token(token):
        return None
    state = request.app.state
    now = state.runtimes.clock.now_ms()
    directory = state.runtimes.backend.directory
    found = directory.session_by_token(token_hash(token), now)
    if found is None:
        return None
    user, session = found
    if user.disabled or now - session.last_seen_at > state.session_idle_ms:
        return None
    if now - session.last_seen_at >= TOUCH_EVERY_MS:
        directory.touch_session(session.id, now)
    request.state.session_id = session.id
    tenants = None if user.tenants is None else frozenset(user.tenants)
    return Caller("user", user.id, user.name, Role[user.role.name], tenants)


def authenticate(request: Request) -> Caller:
    """Who is calling. Raises ``Unauthorized``; a cookie write without the console header is
    ``Forbidden`` (see ``mandate.api.sessions`` on cross-site requests)."""
    provided = request.headers.get(API_KEY_HEADER)
    if provided:
        key = find_key(provided, request.app.state.keyring)
        if key is None:
            raise Unauthorized("missing or invalid API key")
        return key_caller(key)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized("missing or invalid API key")
    caller = session_caller(request, token)
    if caller is None:
        raise Unauthorized("your session has ended; sign in again")
    if request.method not in SAFE_METHODS and request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
        raise Forbidden("this request did not come from the console")
    return caller


def require_caller(request: Request) -> str:
    """FastAPI dependency: authenticate, authorise role and tenant, rate limit. Returns the
    caller's id.

    Order matters: a bad key is 401 before anything else; a good key without the role is 403;
    a good key aimed at a tenant outside its list gets the same 404 a missing tenant would,
    so it cannot probe which tenants exist.
    """
    caller = authenticate(request)
    request.state.caller = caller  # set before the checks, so a refusal is audited too
    route = getattr(request.scope.get("route"), "path", request.url.path)
    needed = required_role(request.method, route)
    if caller.role < needed:
        raise Forbidden(
            f"this {caller.kind} is {caller.role.name.lower()}; {needed.name.lower()} is required"
        )
    tenant_id = request.path_params.get("tenant_id")
    if tenant_id is not None and not caller.allows_tenant(tenant_id):
        raise NotFound("no such tenant")
    global_write = tenant_id is None and request.method not in SAFE_METHODS
    if global_write and not caller.all_tenants and not route.startswith(SELF_SERVICE_PREFIX):
        raise Forbidden("this needs access to every tenant")
    limiter: RateLimiter = request.app.state.limiter
    if not limiter.allow(f"{caller.kind}:{caller.id}"):
        raise RateLimited("too many requests")
    return caller.id
