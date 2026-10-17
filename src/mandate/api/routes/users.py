"""Console users: invite, change role or tenants, disable, reset a password, end sessions.

Only an admin with every tenant manages users. Users are disabled, never deleted, so the
audit trail always names someone who still exists. Nobody can change their own role,
tenants or status, so an admin cannot lock themselves out by accident.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from mandate.api.audit import note_created
from mandate.api.keys import Caller
from mandate.api.routes.auth import directory_of, normalise_email, now_ms
from mandate.api.security import require_caller
from mandate.api.sessions import hash_password
from mandate.errors import BadRequest, Forbidden
from mandate.graph.tenants import tenant_graph_name
from mandate.ids import new_id
from mandate.models.accounts import User
from mandate.models.api import CreateUserIn, PasswordResetIn, UpdateUserIn, UserOut

router = APIRouter(prefix="/v1/users", tags=["users"], dependencies=[Depends(require_caller)])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        tenants=None if user.tenants is None else list(user.tenants),
        disabled=user.disabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _require_global_admin(request: Request) -> Caller:
    caller: Caller = request.state.caller
    if not caller.all_tenants:
        raise Forbidden("managing users needs access to every tenant")
    return caller


def _tenant_list(tenants: list[str] | None) -> tuple[str, ...] | None:
    if tenants is None:
        return None
    cleaned = tuple(sorted({t.strip() for t in tenants if t.strip()}))
    for tenant_id in cleaned:
        tenant_graph_name(tenant_id)  # ValidationFailure for a malformed id
    if not cleaned:
        raise BadRequest("tenants must name at least one tenant, or be null for every tenant")
    return cleaned


@router.get("", response_model=list[UserOut])
def list_users(request: Request) -> list[UserOut]:
    _require_global_admin(request)
    return [user_out(u) for u in directory_of(request).list_users()]


@router.post("", status_code=201, response_model=UserOut)
def create_user(body: CreateUserIn, request: Request) -> UserOut:
    _require_global_admin(request)
    at = now_ms(request)
    user = User(
        id=new_id("usr", now_ms=at),
        email=normalise_email(body.email),
        name=body.name,
        role=body.role,
        tenants=_tenant_list(body.tenants),
        created_at=at,
        updated_at=at,
        password_hash=hash_password(body.password),
    )
    created = directory_of(request).create_user(user)
    note_created(request, created.id)
    return user_out(created)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UpdateUserIn, request: Request) -> UserOut:
    caller = _require_global_admin(request)
    directory = directory_of(request)
    current = directory.get_user(user_id)
    sent = body.model_fields_set
    changes: dict[str, object] = {}
    if "name" in sent and body.name is not None:
        changes["name"] = body.name
    if "role" in sent and body.role is not None:
        changes["role"] = body.role
    if "tenants" in sent:
        changes["tenants"] = _tenant_list(body.tenants)
    if "disabled" in sent and body.disabled is not None:
        changes["disabled"] = body.disabled
    guarded = {"role", "tenants", "disabled"} & changes.keys()
    if caller.kind == "user" and caller.id == user_id and guarded:
        raise BadRequest("you cannot change your own role, tenants or status")
    if not changes:
        return user_out(current)
    updated = current.model_copy(update={**changes, "updated_at": now_ms(request)})
    saved = directory.update_user(User.model_validate(updated.model_dump()))
    if saved.disabled:
        directory.end_sessions(saved.id)  # a disabled user is signed out everywhere at once
    return user_out(saved)


@router.post("/{user_id}/password", response_model=UserOut)
def reset_password(user_id: str, body: PasswordResetIn, request: Request) -> UserOut:
    """Set a new password for someone; every session they had ends."""
    _require_global_admin(request)
    directory = directory_of(request)
    updated = directory.set_password(user_id, hash_password(body.password), now_ms(request))
    directory.end_sessions(user_id)
    return user_out(updated)


@router.post("/{user_id}/sessions/end", response_model=UserOut)
def end_sessions(user_id: str, request: Request) -> UserOut:
    _require_global_admin(request)
    directory = directory_of(request)
    user = directory.get_user(user_id)
    directory.end_sessions(user_id)
    return user_out(user)
