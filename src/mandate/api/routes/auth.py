"""Console sign-in: sign in, sign out, who am I, change my password, my sessions.

A wrong email and a wrong password get the same answer after the same amount of work, and
attempts are limited per email, so the sign-in form cannot be used to find accounts or to
guess passwords quickly.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response

from mandate.api.audit import Actor, set_actor
from mandate.api.keys import Caller
from mandate.api.security import RateLimiter, require_caller, session_caller
from mandate.api.sessions import (
    CLIENT_HEADER,
    CLIENT_VALUE,
    SESSION_COOKIE,
    dummy_hash,
    hash_password,
    new_session_token,
    token_hash,
    verify_password,
)
from mandate.errors import (
    BadRequest,
    Forbidden,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationFailure,
)
from mandate.ids import new_id
from mandate.models.accounts import ActorKind, Directory, Session, User, UserRole
from mandate.models.api import LoginIn, MeOut, PasswordChangeIn, SessionOut
from mandate.observability import metrics

router = APIRouter(prefix="/v1/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")


def normalise_email(raw: str) -> str:
    email = raw.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValidationFailure("email: not a valid email address")
    return email


def directory_of(request: Request) -> Directory:
    directory: Directory = request.app.state.runtimes.backend.directory
    return directory


def now_ms(request: Request) -> int:
    return int(request.app.state.runtimes.clock.now_ms())


def me_for_user(user: User) -> MeOut:
    return MeOut(
        kind="user",
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        tenants=None if user.tenants is None else list(user.tenants),
    )


def start_session(request: Request, response: Response, user: User) -> Session:
    state = request.app.state
    now = now_ms(request)
    token = new_session_token()
    agent = request.headers.get("user-agent")
    session = directory_of(request).create_session(
        Session(
            id=new_id("ses", now_ms=now),
            user_id=user.id,
            token_hash=token_hash(token),
            created_at=now,
            expires_at=now + state.session_ttl * 1000,
            last_seen_at=now,
            user_agent=agent[:200] if agent else None,
        ),
        now,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=state.session_ttl,
        httponly=True,
        secure=state.cookie_secure,
        samesite="strict",
        path="/",
    )
    return session


def end_session(request: Request, response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="strict",
    )


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response) -> MeOut:
    if request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
        # Not from the console: refuse before any work, so another site cannot sign a visitor
        # in to an account of its choosing.
        raise Forbidden("sign in from the console")
    email = normalise_email(body.email)
    set_actor(request, Actor(ActorKind.ANONYMOUS, None, email))
    limiter: RateLimiter = request.app.state.login_limiter
    if not limiter.allow(f"email:{email}"):
        metrics.SIGN_INS.labels("limited").inc()
        raise RateLimited("too many sign-in attempts; wait a minute and try again")
    directory = directory_of(request)
    user = directory.find_user_by_email(email)
    matches = verify_password(body.password, user.password_hash if user else dummy_hash())
    if user is None or not matches or user.disabled:
        metrics.SIGN_INS.labels("denied").inc()
        raise Unauthorized("the email or password is incorrect")
    set_actor(request, Actor(ActorKind.USER, user.id, user.name))
    directory.record_login(user.id, now_ms(request))
    start_session(request, response, user)
    metrics.SIGN_INS.labels("success").inc()
    return me_for_user(user)


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    """Ends this browser's session on the server. Safe to call when already signed out."""
    response = Response(status_code=204)
    token = request.cookies.get(SESSION_COOKIE)
    caller = session_caller(request, token) if token else None
    if caller is not None:
        set_actor(request, Actor(ActorKind.USER, caller.id, caller.name))
        directory_of(request).end_session(caller.id, request.state.session_id)
    end_session(request, response)
    return response


@router.get("/me", response_model=MeOut, dependencies=[Depends(require_caller)])
def me(request: Request) -> MeOut:
    caller: Caller = request.state.caller
    if caller.kind == "user":
        return me_for_user(directory_of(request).get_user(caller.id))
    return MeOut(
        kind="key",
        id=caller.id,
        name=caller.name,
        role=UserRole[caller.role.name],
        tenants=None if caller.tenants is None else sorted(caller.tenants),
    )


def _signed_in_user(request: Request) -> User:
    caller: Caller = request.state.caller
    if caller.kind != "user":
        raise BadRequest("an API key has no password or sessions; sign in as a user")
    return directory_of(request).get_user(caller.id)


@router.post("/password", response_model=MeOut, dependencies=[Depends(require_caller)])
def change_password(body: PasswordChangeIn, request: Request) -> MeOut:
    """Every other session ends; this one continues."""
    user = _signed_in_user(request)
    limiter: RateLimiter = request.app.state.login_limiter
    if not limiter.allow(f"email:{user.email}"):
        raise RateLimited("too many attempts; wait a minute and try again")
    if not verify_password(body.current_password, user.password_hash):
        raise BadRequest("the current password is incorrect")
    if body.new_password == body.current_password:
        raise BadRequest("the new password must differ from the current one")
    directory = directory_of(request)
    updated = directory.set_password(user.id, hash_password(body.new_password), now_ms(request))
    directory.end_sessions(user.id, keep=request.state.session_id)
    return me_for_user(updated)


@router.get("/sessions", response_model=list[SessionOut], dependencies=[Depends(require_caller)])
def my_sessions(request: Request) -> list[SessionOut]:
    """Where I am signed in, most recently active first."""
    user = _signed_in_user(request)
    current = request.state.session_id
    return [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            user_agent=s.user_agent,
            current=s.id == current,
        )
        for s in directory_of(request).list_sessions(user.id, now_ms(request))
    ]


@router.delete("/sessions/{session_id}", status_code=204, dependencies=[Depends(require_caller)])
def end_one_session(session_id: str, request: Request) -> Response:
    """Sign out one browser. Ending the current one signs this browser out too."""
    user = _signed_in_user(request)
    if not directory_of(request).end_session(user.id, session_id):
        raise NotFound("no such session")
    response = Response(status_code=204)
    if session_id == request.state.session_id:
        end_session(request, response)
    return response


@router.post("/sessions/end", status_code=204, dependencies=[Depends(require_caller)])
def end_all_sessions(request: Request) -> Response:
    """Sign out everywhere, this browser included."""
    user = _signed_in_user(request)
    directory_of(request).end_sessions(user.id)
    response = Response(status_code=204)
    end_session(request, response)
    return response
