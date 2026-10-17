"""Approval links: a signed, expiring capability to approve or decline one held action.

When an action is held, the owner may not be at the console. An admin-key holder (the
console, or a notifier that messages the owner) mints a link for that one action and that
one approver. Whoever opens it can see the action and approve or decline it, and nothing
else: no API key travels with it.

* **Bound.** The tenant, the action and the approving owner are inside the signature, so a
  link cannot be pointed at another action, tenant or person.
* **Expiring.** Fifteen minutes by default, a day at most.
* **Single use.** Resolving moves the action out of ``pending`` in one atomic write, so the
  first use wins and every later use, of this link or any other for the same action, is a
  conflict.
* **Separate key.** Signed with a key derived from each agent-token secret under its own
  label, so an agent token is never a valid link and a link is never a valid agent token.

The console puts the token in the URL fragment (``/approve#apl1...``), which browsers do not
send to servers, so it stays out of access logs; the page posts it in a request body.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Sequence
from dataclasses import dataclass

from mandate.ids import is_valid_id

PREFIX = "apl1"
LABEL = b"mandate/approval-link/v1"
SIGNATURE_BYTES = 16
DEFAULT_TTL_SECONDS = 15 * 60
MAX_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class ApprovalLink:
    tenant_id: str
    action_id: str
    approver_id: str
    expires_at: int  # epoch seconds


def link_secrets(token_secrets: Sequence[str]) -> list[str]:
    """One link key per agent-token secret, newest first, so links rotate with them."""
    return [hmac.new(s.encode(), LABEL, hashlib.sha256).hexdigest() for s in token_secrets]


def _sign(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return digest[:SIGNATURE_BYTES].hex()


def mint_link(
    secret: str,
    tenant_id: str,
    action_id: str,
    approver_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> tuple[str, ApprovalLink]:
    if "|" in tenant_id or not is_valid_id(action_id, "act"):
        raise ValueError("a tenant id and an action id are required")
    if not is_valid_id(approver_id, "prn"):
        raise ValueError("the approver must be a principal id")
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    expires = int((time.time() if now is None else now) + ttl_seconds)
    raw = f"{tenant_id}|{action_id}|{approver_id}|{expires}"
    payload = base64.urlsafe_b64encode(raw.encode()).decode()
    link = ApprovalLink(tenant_id, action_id, approver_id, expires)
    return f"{PREFIX}.{payload}.{_sign(secret, payload)}", link


def read_link(
    secrets: Sequence[str], token: str | None, *, now: float | None = None
) -> ApprovalLink | None:
    """What a valid, unexpired link names, or None for anything else (never raises)."""
    try:
        prefix, payload, signature = (token or "").split(".")
        if prefix != PREFIX:
            return None
        signed = False
        for secret in secrets:  # every one, so timing does not reveal which matched
            signed = hmac.compare_digest(signature, _sign(secret, payload)) or signed
        if not signed:
            return None
        raw = base64.urlsafe_b64decode(payload.encode()).decode()
        tenant_id, action_id, approver_id, expires = raw.split("|")
        expires_at = int(expires)
    except ValueError:
        return None
    if (time.time() if now is None else now) >= expires_at:
        return None
    if not (tenant_id and is_valid_id(action_id, "act") and is_valid_id(approver_id, "prn")):
        return None
    return ApprovalLink(tenant_id, action_id, approver_id, expires_at)
