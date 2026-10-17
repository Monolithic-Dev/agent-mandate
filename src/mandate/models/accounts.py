"""Console accounts and the audit trail (docs/security-privacy.md section 2).

People sign in to the console as users; every change anyone makes, through the console or
with an API key, becomes an audit event. Both live in the registry graph next to the tenants,
because they span tenants. This module has no I/O: ``Directory`` is the port the graph
adapter and the in-memory fake implement.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import ConfigDict, Field

from mandate.models.nul_free import NulFreeModel
from mandate.models.webhooks import Delivery, Webhook

EMAIL_MAX = 254
PASSWORD_MIN = 12
PASSWORD_MAX = 256


class UserRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class ActorKind(StrEnum):
    USER = "user"
    KEY = "key"
    LINK = "link"  # an owner acting through an approval link
    CLI = "cli"  # someone on the server, with python -m mandate.users
    ANONYMOUS = "anonymous"  # a failed sign-in


class Outcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"  # refused: unauthorised, forbidden, or a bad password
    FAILED = "failed"  # accepted but went wrong (validation, conflict, server error)


class User(NulFreeModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    name: str = Field(min_length=1, max_length=80)
    role: UserRole
    tenants: tuple[str, ...] | None = None  # None means every tenant
    disabled: bool = False
    created_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)
    last_login_at: int | None = None
    password_hash: str = Field(repr=False)


class Session(NulFreeModel):
    """A signed-in browser. The cookie holds a random token; only its hash is stored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    user_id: str
    token_hash: str = Field(repr=False)
    created_at: int = Field(ge=0)
    expires_at: int = Field(ge=0)
    last_seen_at: int = Field(ge=0)
    user_agent: str | None = Field(default=None, max_length=200)


class AuditEvent(NulFreeModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    at: int = Field(ge=0)
    actor_kind: ActorKind
    actor_id: str | None = None
    actor_name: str | None = None
    action: str  # a stable name such as "rule.confirm"; see mandate.api.audit
    method: str
    route: str
    tenant_id: str | None = None
    target: str | None = None  # the id the request was about, when it names one
    status: int
    outcome: Outcome
    request_id: str | None = None


class Directory(Protocol):
    """Users and audit events, shared by every tenant."""

    def create_user(self, user: User) -> User:
        """Raises ``Conflict`` if a user already has this email."""
        ...

    def get_user(self, user_id: str) -> User:
        """Raises ``NotFound``."""
        ...

    def find_user_by_email(self, email: str) -> User | None: ...

    def list_users(self) -> list[User]: ...

    def update_user(self, user: User) -> User:
        """Replace name, role, tenants, disabled, updated_at. Raises ``NotFound``."""
        ...

    def set_password(self, user_id: str, password_hash: str, at: int) -> User:
        """Store a new hash. Raises ``NotFound``. Ending sessions is the caller's choice."""
        ...

    # --- sessions ---

    def create_session(self, session: Session, now: int) -> Session:
        """Store a session (and drop the user's expired ones). Raises ``NotFound``."""
        ...

    def session_by_token(self, token_hash: str, now: int) -> tuple[User, Session] | None:
        """The live session with this token hash, and its user."""
        ...

    def touch_session(self, session_id: str, at: int) -> None: ...

    def list_sessions(self, user_id: str, now: int) -> list[Session]:
        """Live sessions, most recently seen first."""
        ...

    def end_session(self, user_id: str, session_id: str) -> bool:
        """End one of this user's sessions; False if they have no such session."""
        ...

    def end_sessions(self, user_id: str, keep: str | None = None) -> int:
        """End all of a user's sessions but ``keep``; returns how many ended."""
        ...

    def record_login(self, user_id: str, at: int) -> None: ...

    def record_audit(self, event: AuditEvent) -> None: ...

    # --- webhooks ---

    def create_webhook(self, webhook: Webhook) -> Webhook:
        """Raises ``NotFound`` if the tenant does not exist."""
        ...

    def list_webhooks(
        self, *, tenant_id: str | None = None, enabled: bool | None = None
    ) -> list[Webhook]:
        """Oldest first."""
        ...

    def get_webhook(self, webhook_id: str) -> Webhook:
        """Raises ``NotFound``."""
        ...

    def update_webhook(self, webhook: Webhook) -> Webhook:
        """Replace name, events and enabled. Raises ``NotFound``."""
        ...

    def record_progress(
        self, webhook_id: str, *, cursor: str, at: int | None, ok: bool | None, failures: int
    ) -> None:
        """After a delivery round: the newest action announced, and how it went."""
        ...

    def delete_webhooks(
        self, *, webhook_id: str | None = None, tenant_id: str | None = None
    ) -> int:
        """Delete one webhook, or every webhook of a tenant, with their deliveries."""
        ...

    def record_delivery(self, delivery: Delivery, keep: int) -> None:
        """Store it, and keep only the newest ``keep`` deliveries of its webhook."""
        ...

    def list_deliveries(self, webhook_id: str, limit: int) -> list[Delivery]:
        """Newest first."""
        ...

    def list_audit(
        self,
        *,
        tenant_ids: frozenset[str] | None,
        tenant_id: str | None,
        actor_id: str | None,
        action: str | None,
        before: str | None,
        limit: int,
    ) -> list[AuditEvent]:
        """Newest first. ``tenant_ids`` limits a scoped caller to its tenants (and hides
        events that concern no tenant); ``before`` is an event id to page from."""
        ...
