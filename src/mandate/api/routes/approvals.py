"""Approval links (see ``mandate.api.approval_links``).

Minting needs an admin key. Opening and using a link needs only the link: it is the
credential, scoped to one held action, one tenant and one approving owner.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from mandate.api.approval_links import DEFAULT_TTL_SECONDS, ApprovalLink, mint_link, read_link
from mandate.api.audit import Actor, set_actor
from mandate.api.routes.authority import runtime_for
from mandate.api.security import RateLimiter, require_caller
from mandate.api.tenancy import Runtimes, TenantRuntime
from mandate.errors import Conflict, NotFound, RateLimited, Unauthorized
from mandate.gateway.guard import resolve_pending
from mandate.models.accounts import ActorKind
from mandate.models.api import ApprovalLinkIn, ApprovalLinkOut, LinkIn, LinkResolveIn
from mandate.models.domain import ActionStatus

tenant_router = APIRouter(
    prefix="/v1/tenants/{tenant_id}", tags=["approvals"], dependencies=[Depends(require_caller)]
)
router = APIRouter(prefix="/v1/approval-links", tags=["approvals"])


@tenant_router.post(
    "/actions/{action_id}/approval-link", status_code=201, response_model=ApprovalLinkOut
)
def create_link(
    tenant_id: str, action_id: str, body: ApprovalLinkIn, request: Request
) -> ApprovalLinkOut:
    runtime = runtime_for(tenant_id, request)
    runtime.service.require_owner(body.by)
    if runtime.store.get_action(action_id).action.status is not ActionStatus.PENDING:
        raise Conflict("this action is not waiting for approval")
    token, link = mint_link(
        request.app.state.link_secrets[0],
        tenant_id,
        action_id,
        body.by,
        ttl_seconds=body.ttl_seconds or DEFAULT_TTL_SECONDS,
    )
    return ApprovalLinkOut(token=token, expires_at=link.expires_at, path=f"/approve#{token}")


def _open(token: str, request: Request) -> tuple[ApprovalLink, TenantRuntime]:
    """The link and its tenant's runtime, or one error for every kind of bad link."""
    limiter: RateLimiter = request.app.state.limiter
    if not limiter.allow(f"link:{request.client.host if request.client else '-'}"):
        raise RateLimited("too many requests")
    link = read_link(request.app.state.link_secrets, token)
    if link is None:
        raise Unauthorized("this approval link is not valid or has expired")
    runtimes: Runtimes = request.app.state.runtimes
    try:
        return link, runtimes.require(link.tenant_id)
    except NotFound:
        raise Unauthorized("this approval link is not valid or has expired") from None


@router.post("/inspect")
def inspect_link(body: LinkIn, request: Request) -> dict[str, Any]:
    """What the link would approve: the action, who proposed it, why it is held, for whom."""
    link, runtime = _open(body.token, request)
    stored = runtime.store.get_action(link.action_id)
    narrative = (
        runtime.service.explain(stored.decision_id).narrative if stored.decision_id else None
    )
    return {
        "tenant_id": link.tenant_id,
        "action": stored.action.model_dump(mode="json"),  # the tool and its arguments
        "agent": runtime.store.get_agent(stored.agent_id).model_dump(mode="json"),
        "decision_id": stored.decision_id,
        "narrative": narrative,
        "approver": runtime.store.get_principal(link.approver_id).model_dump(mode="json"),
        "expires_at": link.expires_at,
        "pending": stored.action.status is ActionStatus.PENDING,
    }


@router.post("/resolve")
def resolve_link(body: LinkResolveIn, request: Request) -> dict[str, Any]:
    """Approve or decline. The first use wins; any later use is a 409."""
    link, runtime = _open(body.token, request)
    approver = runtime.store.get_principal(link.approver_id)
    set_actor(
        request,
        Actor(ActorKind.LINK, approver.id, approver.name, link.tenant_id, link.action_id),
    )
    result = resolve_pending(
        runtime.gateway, link.action_id, link.approver_id, approved=body.approved
    )
    return result.to_dict()
