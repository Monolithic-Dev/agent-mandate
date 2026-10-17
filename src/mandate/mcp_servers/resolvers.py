"""How each transport establishes who is calling.

Over stdio the identity is fixed when the process starts (the parent process chose it).
Over HTTP every call must carry credentials, checked on every call.
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Sequence
from typing import Any

from mcp.server.mcpserver import Context

from mandate.mcp_servers.admin_server import AdminIdentity, IdentifyAdmin
from mandate.mcp_servers.agent_server import Identify
from mandate.mcp_servers.identity import AgentIdentity, bearer_token, verify_agent_token


def static_agent(identity: AgentIdentity) -> Identify:
    """A fixed identity (stdio). A token's expiry still applies for as long as the process runs."""

    def identify(ctx: Context[Any]) -> AgentIdentity:
        if identity.expires_at is not None and time.time() >= identity.expires_at:
            raise PermissionError("the agent token has expired")
        return identity

    return identify


def static_admin(identity: AdminIdentity) -> IdentifyAdmin:
    return lambda ctx: identity


def http_agent(secrets: str | Sequence[str]) -> Identify:
    def identify(ctx: Context[Any]) -> AgentIdentity:
        headers = ctx.headers or {}
        who = verify_agent_token(secrets, bearer_token(headers.get("authorization")))
        if who is None:
            raise PermissionError("missing or invalid agent token")
        return who

    return identify


def http_admin(api_key: str) -> IdentifyAdmin:
    """Owner calls carry the admin key plus the tenant and owner they act for."""

    def identify(ctx: Context[Any]) -> AdminIdentity:
        headers = ctx.headers or {}
        presented = bearer_token(headers.get("authorization")) or ""
        if not hmac.compare_digest(presented.encode(), api_key.encode()):
            raise PermissionError("missing or invalid admin key")
        tenant, owner = headers.get("x-mandate-tenant"), headers.get("x-mandate-owner")
        if not tenant or not owner:
            raise PermissionError("x-mandate-tenant and x-mandate-owner headers are required")
        return AdminIdentity(tenant, owner)

    return identify
