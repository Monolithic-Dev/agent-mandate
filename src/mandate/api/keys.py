"""API keys with a role and a tenant allow-list.

A key is ``id:secret:role:tenants`` (several keys separated by ``;``), for example
``reader:s3cr3t...:viewer:acme,globex``. ``tenants`` is ``*`` or a comma list. The admin key
from ``MANDATE_API_KEY`` is always present with role ``admin`` and every tenant.

Roles, lowest to highest:

* ``viewer``: read-only (GET).
* ``operator``: viewer, plus run agents' tool calls and checks (what an agent runtime needs).
* ``admin``: everything, including saying rules, approving, revoking, quarantining and
  creating or deleting tenants.

One table (``required_role``) decides what each request needs, so a new route cannot quietly
skip authorisation: anything that is not clearly a read or an agent call needs ``admin``, and
the user directory and the audit trail need ``admin`` even to read.

A console user signed in with a password gets the same roles (``mandate.api.sessions``); both
kinds of caller become a ``Caller``, so the rest of the API does not care which it was.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import IntEnum

from mandate.errors import ConfigError

MIN_SECRET_LENGTH = 16


class Role(IntEnum):
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3


@dataclass(frozen=True)
class ApiKey:
    id: str
    secret: str
    role: Role
    tenants: frozenset[str] | None  # None means every tenant

    def allows_tenant(self, tenant_id: str) -> bool:
        return self.tenants is None or tenant_id in self.tenants

    @property
    def all_tenants(self) -> bool:
        return self.tenants is None


ADMIN_ONLY_PREFIXES = ("/v1/users", "/v1/audit")
SELF_SERVICE_PREFIX = "/v1/auth/"  # anyone signed in manages their own session and password


@dataclass(frozen=True)
class Caller:
    """Whoever made a request: an API key or a signed-in console user."""

    kind: str  # "key" or "user"
    id: str
    name: str
    role: Role
    tenants: frozenset[str] | None  # None means every tenant

    def allows_tenant(self, tenant_id: str) -> bool:
        return self.tenants is None or tenant_id in self.tenants

    @property
    def all_tenants(self) -> bool:
        return self.tenants is None


def key_caller(key: ApiKey) -> Caller:
    return Caller("key", key.id, f"API key {key.id}", key.role, key.tenants)


def required_role(method: str, path_template: str) -> Role:
    """The lowest role that may make this request."""
    if path_template.startswith(ADMIN_ONLY_PREFIXES) or "/webhooks" in path_template:
        return Role.ADMIN  # webhook URLs and secrets are credentials, even to read
    if path_template.startswith(SELF_SERVICE_PREFIX):
        return Role.VIEWER
    if method in ("GET", "HEAD"):
        return Role.VIEWER
    # Agents' calls, and trying things out without changing anything: the simulator's dry-run
    # check and the preview of a sentence (which runs on a throwaway copy of the graph).
    if method == "POST" and path_template.endswith(("/tool-calls", "/check", "/preview")):
        return Role.OPERATOR
    return Role.ADMIN


def build_keyring(admin_secret: str, extra: str | None) -> list[ApiKey]:
    """The admin key plus any keys from ``MANDATE_API_KEYS``. Raises ``ConfigError``."""
    ring = [ApiKey("admin", admin_secret, Role.ADMIN, None)]
    for entry in (part.strip() for part in (extra or "").split(";")):
        if not entry:
            continue
        pieces = entry.split(":", 3)
        if len(pieces) != 4:
            raise ConfigError("each MANDATE_API_KEYS entry must be id:secret:role:tenants")
        key_id, secret, role_name, tenant_spec = (p.strip() for p in pieces)
        try:
            role = Role[role_name.upper()]
        except KeyError:
            raise ConfigError(f"unknown role {role_name!r} for key {key_id!r}") from None
        if not key_id or len(secret) < MIN_SECRET_LENGTH:
            raise ConfigError(
                f"key {key_id!r}: an id and a secret of at least {MIN_SECRET_LENGTH} characters"
            )
        tenants = (
            None
            if tenant_spec == "*"
            else frozenset(t.strip() for t in tenant_spec.split(",") if t.strip())
        )
        if tenants is not None and not tenants:
            raise ConfigError(f"key {key_id!r}: tenants must be * or a list")
        ring.append(ApiKey(key_id, secret, role, tenants))
    if len({k.id for k in ring}) != len(ring) or len({k.secret for k in ring}) != len(ring):
        raise ConfigError("API key ids and secrets must be unique")
    return ring


def find_key(provided: str | None, ring: list[ApiKey]) -> ApiKey | None:
    """Constant-time lookup: every key is compared, so timing does not reveal which matched."""
    if not provided:
        return None
    match: ApiKey | None = None
    for key in ring:
        if hmac.compare_digest(provided.encode(), key.secret.encode()):
            match = key
    return match
