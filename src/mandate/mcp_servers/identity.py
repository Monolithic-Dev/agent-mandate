"""Agent identity bound to a signed, expiring token.

An agent never states who it is: the token names the tenant and agent, and is signed with a
server secret, so a tool call cannot be made "as" another agent. The admin mints tokens.

* **Expiry.** Every token carries an expiry time (seconds since the epoch) inside the signed
  payload; an expired token is rejected like a forged one.
* **Rotation.** Secrets are tried newest first when verifying and the newest signs. To rotate,
  put the new secret first and keep the old one in the list until the longest-lived token
  signed with it has expired, then drop it.
* **Revocation.** Every token has its own id (``tok_...``), signed with the rest. The owner can
  revoke one token by that id; the servers look the id up on every call. Tokens minted before
  ids existed (prefix ``mnd2``) still verify until they expire but cannot be revoked one by
  one: rotate the secret to kill them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mandate.errors import BadRequest
from mandate.ids import is_valid_id, new_id

if TYPE_CHECKING:
    from mandate.authority.service import AuthorityService

PREFIX = "mnd3"
LEGACY_PREFIX = "mnd2"  # tenant|agent|expiry, no token id
SIGNATURE_BYTES = 16
DEFAULT_TTL_SECONDS = 86_400
MAX_TTL_SECONDS = 30 * 86_400


@dataclass(frozen=True)
class AgentIdentity:
    tenant_id: str
    agent_id: str
    expires_at: int | None = None  # epoch seconds; set when read from a token
    token_id: str | None = None  # set when read from a token that has one


def _sign(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return digest[:SIGNATURE_BYTES].hex()


def mint_agent_token(
    secret: str,
    identity: AgentIdentity,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    return mint_agent_token_with_id(secret, identity, ttl_seconds=ttl_seconds, now=now)[0]


def mint_agent_token_with_id(
    secret: str,
    identity: AgentIdentity,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> tuple[str, AgentIdentity]:
    """A token and the identity it names, with its id and expiry (to show the owner)."""
    if "|" in identity.tenant_id or "|" in identity.agent_id:
        raise ValueError("ids may not contain '|'")
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    issued = time.time() if now is None else now
    expires = int(issued + ttl_seconds)
    token_id = new_id("tok", now_ms=int(issued * 1000))
    raw = f"{identity.tenant_id}|{identity.agent_id}|{token_id}|{expires}"
    payload = base64.urlsafe_b64encode(raw.encode()).decode()
    token = f"{PREFIX}.{payload}.{_sign(secret, payload)}"
    return token, AgentIdentity(identity.tenant_id, identity.agent_id, expires, token_id)


def verify_agent_token(
    secrets: str | Sequence[str], token: str | None, *, now: float | None = None
) -> AgentIdentity | None:
    """The identity a valid, unexpired token names, or None for anything else (never raises).

    Whether the token has been revoked is not known here: that needs the tenant's graph.
    """
    ring = [secrets] if isinstance(secrets, str) else list(secrets)
    try:
        prefix, payload, signature = (token or "").split(".")
        if prefix not in (PREFIX, LEGACY_PREFIX):
            return None
        # Compare against every secret so timing does not reveal which one matched.
        signed = False
        for secret in ring:
            signed = hmac.compare_digest(signature, _sign(secret, payload)) or signed
        if not signed:
            return None
        fields = base64.urlsafe_b64decode(payload.encode()).decode().split("|")
        token_id: str | None = None
        if prefix == PREFIX:
            tenant_id, agent_id, token_id, expires = fields
            if not is_valid_id(token_id, "tok"):
                return None
        else:
            tenant_id, agent_id, expires = fields
        expires_at = int(expires)
    except ValueError:
        return None
    if (time.time() if now is None else now) >= expires_at:
        return None
    if not (tenant_id and agent_id):
        return None
    return AgentIdentity(tenant_id, agent_id, expires_at, token_id)


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization[:7].lower() == "bearer ":
        return authorization[7:].strip()
    return None


def revoke_token(
    service: AuthorityService,
    tenant_id: str,
    owner_id: str,
    token_id: str | None,
    token: str | None,
    secrets: str | Sequence[str],
) -> dict[str, Any]:
    """Revoke an agent token named by id, or by the token string (which must be this
    tenant's and still valid). Shared by the admin MCP server and the REST API."""
    agent_id: str | None = None
    expires_at_ms: int | None = None
    if token is not None:
        named = verify_agent_token(secrets, token)
        if named is None or named.tenant_id != tenant_id:
            raise BadRequest("not a valid, unexpired agent token for this tenant")
        if named.token_id is None:
            raise BadRequest("this token has no id; rotate the signing secret to revoke it")
        if token_id is not None and token_id != named.token_id:
            raise BadRequest("token_id does not match the token")
        token_id, agent_id = named.token_id, named.agent_id
        expires_at_ms = None if named.expires_at is None else named.expires_at * 1000
    if token_id is None:
        raise BadRequest("give token_id or token")
    if not is_valid_id(token_id, "tok"):
        raise BadRequest("token_id must look like tok_...")
    done = service.revoke_token(token_id, owner_id, agent_id=agent_id, expires_at_ms=expires_at_ms)
    return done.model_dump(mode="json")
