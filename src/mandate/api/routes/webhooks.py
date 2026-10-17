"""A tenant's webhooks: add, list, change, remove, send a test, read the delivery log.

Admins only, reads included: a Slack webhook URL is itself a credential, so it is shown
masked after it is saved, and a JSON webhook's signing secret is shown once, when created.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from mandate.api.audit import note_created
from mandate.api.keys import Caller
from mandate.api.notify import Notifier, check_url, mask_url
from mandate.api.routes.auth import directory_of, now_ms
from mandate.api.routes.authority import runtime_for
from mandate.api.security import require_caller
from mandate.errors import NotFound
from mandate.ids import new_id
from mandate.models.api import WebhookIn, WebhookPatch
from mandate.models.webhooks import Webhook, WebhookEvent

router = APIRouter(
    prefix="/v1/tenants/{tenant_id}/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(require_caller)],
)


def webhook_out(hook: Webhook, *, secret: bool = False) -> dict[str, Any]:
    body = hook.model_dump(mode="json", exclude={"url", "secret"})
    body["url"] = mask_url(hook.url)
    if secret:
        body["secret"] = hook.secret
    return body


def _notifier(request: Request) -> Notifier:
    notifier: Notifier = request.app.state.notifier
    return notifier


def _hook(tenant_id: str, webhook_id: str, request: Request) -> Webhook:
    runtime_for(tenant_id, request)
    hook = directory_of(request).get_webhook(webhook_id)
    if hook.tenant_id != tenant_id:
        raise NotFound("no such webhook")
    return hook


@router.get("")
def list_webhooks(tenant_id: str, request: Request) -> list[dict[str, Any]]:
    runtime_for(tenant_id, request)
    return [webhook_out(h) for h in directory_of(request).list_webhooks(tenant_id=tenant_id)]


@router.post("", status_code=201)
def create_webhook(tenant_id: str, body: WebhookIn, request: Request) -> dict[str, Any]:
    runtime_for(tenant_id, request)
    url = check_url(body.url, allow_private=request.app.state.webhook_allow_private)
    caller: Caller = request.state.caller
    at = now_ms(request)
    hook = Webhook(
        id=new_id("whk", now_ms=at),
        tenant_id=tenant_id,
        name=body.name,
        url=url,
        kind=body.kind,
        events=tuple(dict.fromkeys(body.events)),
        secret="whsec_" + secrets.token_urlsafe(24),
        enabled=True,
        created_at=at,
        created_by=f"{caller.kind}:{caller.id}",
        # Announce what is held from now on, not what was already waiting.
        cursor=_notifier(request).start_cursor(tenant_id),
    )
    created = directory_of(request).create_webhook(hook)
    note_created(request, created.id)
    return webhook_out(created, secret=True)


@router.patch("/{webhook_id}")
def update_webhook(
    tenant_id: str, webhook_id: str, body: WebhookPatch, request: Request
) -> dict[str, Any]:
    hook = _hook(tenant_id, webhook_id, request)
    changes: dict[str, Any] = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.events is not None:
        changes["events"] = tuple(dict.fromkeys(body.events))
    if body.enabled is not None:
        changes["enabled"] = body.enabled
        if body.enabled and not hook.enabled:
            # Turned back on: start from now, rather than replaying what it missed.
            directory_of(request).record_progress(
                hook.id,
                cursor=_notifier(request).start_cursor(tenant_id),
                at=hook.last_delivery_at,
                ok=hook.last_ok,
                failures=0,
            )
    updated = directory_of(request).update_webhook(hook.model_copy(update=changes))
    return webhook_out(updated)


@router.delete("/{webhook_id}", status_code=204)
def delete_webhook(tenant_id: str, webhook_id: str, request: Request) -> Response:
    _hook(tenant_id, webhook_id, request)
    directory_of(request).delete_webhooks(webhook_id=webhook_id)
    return Response(status_code=204)


@router.post("/{webhook_id}/test")
def test_webhook(tenant_id: str, webhook_id: str, request: Request) -> dict[str, Any]:
    """Send a ping now and say how it went."""
    hook = _hook(tenant_id, webhook_id, request)
    delivery = _notifier(request).deliver(hook, WebhookEvent.TEST, None)
    return delivery.model_dump(mode="json")


@router.get("/{webhook_id}/deliveries")
def list_deliveries(
    tenant_id: str, webhook_id: str, request: Request, limit: int = 20
) -> list[dict[str, Any]]:
    _hook(tenant_id, webhook_id, request)
    rows = directory_of(request).list_deliveries(webhook_id, max(1, min(limit, 50)))
    return [row.model_dump(mode="json") for row in rows]
