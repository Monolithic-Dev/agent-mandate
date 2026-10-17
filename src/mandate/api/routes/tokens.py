"""Agent tokens: mint one for an agent, revoke one before it expires.

The MCP agent server accepts these tokens; the REST API never does (it takes API keys). The
owner revokes a single token by its id, and the agent server refuses it from its next call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from mandate.api.audit import note_created
from mandate.api.routes.authority import runtime_for
from mandate.api.security import require_caller
from mandate.errors import BadRequest
from mandate.mcp_servers.identity import AgentIdentity, mint_agent_token_with_id, revoke_token
from mandate.models.api import MintTokenIn, RevokeTokenIn, TokenOut

router = APIRouter(
    prefix="/v1/tenants/{tenant_id}", tags=["tokens"], dependencies=[Depends(require_caller)]
)


@router.post("/agents/{agent_id}/tokens", status_code=201, response_model=TokenOut)
def mint_token(tenant_id: str, agent_id: str, body: MintTokenIn, request: Request) -> TokenOut:
    runtime = runtime_for(tenant_id, request)
    runtime.service.require_owner(body.by)
    runtime.store.get_agent(agent_id)  # NotFound for an agent of another tenant
    ttl = body.ttl_seconds or request.app.state.token_ttl_seconds
    try:
        token, minted = mint_agent_token_with_id(
            request.app.state.token_secrets[0], AgentIdentity(tenant_id, agent_id), ttl_seconds=ttl
        )
    except ValueError as error:
        raise BadRequest(str(error)) from None
    assert minted.token_id is not None and minted.expires_at is not None
    note_created(request, minted.token_id)
    return TokenOut(
        token=token, token_id=minted.token_id, agent_id=agent_id, expires_at=minted.expires_at
    )


@router.post("/token-revocations")
def revoke(tenant_id: str, body: RevokeTokenIn, request: Request) -> dict[str, Any]:
    runtime = runtime_for(tenant_id, request)
    return revoke_token(
        runtime.service,
        tenant_id,
        body.by,
        body.token_id,
        body.token,
        request.app.state.token_secrets,
    )


@router.get("/token-revocations")
def list_revocations(tenant_id: str, request: Request, limit: int = 100) -> list[dict[str, Any]]:
    runtime = runtime_for(tenant_id, request)
    rows = runtime.store.list_token_revocations(max(1, min(limit, 500)))
    return [row.model_dump(mode="json") for row in rows]
