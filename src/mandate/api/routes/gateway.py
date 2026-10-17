"""Tool calls through the gateway, and the owner's approval of held actions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from mandate.api.errors import request_id_of
from mandate.api.routes.authority import runtime_for
from mandate.api.security import require_caller
from mandate.gateway.guard import guarded_call, resolve_pending
from mandate.models.api import ApproveIn, ToolCallIn
from mandate.models.domain import ActionStatus

router = APIRouter(
    prefix="/v1/tenants/{tenant_id}", tags=["gateway"], dependencies=[Depends(require_caller)]
)


@router.post("/tool-calls")
def tool_call(tenant_id: str, body: ToolCallIn, request: Request) -> dict[str, Any]:
    """Run a tool as an agent. The outcome (ok, held, denied, error) is in the body."""
    runtime = runtime_for(tenant_id, request)
    result = guarded_call(
        runtime.gateway, body.agent_id, body.tool, body.args, request_id=request_id_of(request)
    )
    return result.to_dict()


@router.get("/actions")
def list_actions(
    tenant_id: str, request: Request, status: ActionStatus | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    runtime = runtime_for(tenant_id, request)
    rows = runtime.store.list_actions(status=status, limit=max(1, min(limit, 200)))
    return [
        {
            "action": row.action.model_dump(mode="json"),
            "agent_id": row.agent_id,
            "decision_id": row.decision_id,
        }
        for row in rows
    ]


@router.post("/actions/{action_id}/approve")
def approve_action(
    tenant_id: str, action_id: str, body: ApproveIn, request: Request
) -> dict[str, Any]:
    runtime = runtime_for(tenant_id, request)
    result = resolve_pending(runtime.gateway, action_id, body.by, approved=body.approved)
    return result.to_dict()
