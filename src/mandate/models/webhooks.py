"""Webhooks: tell the owner, in Slack or any HTTPS endpoint, that something waits for them.

A webhook belongs to one tenant. Today it carries one kind of news, ``approval.requested``
(an agent's action is held for the owner), with a one-time approval link, plus the
``webhook.test`` ping. Each delivery is recorded. This module has no I/O.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field

from mandate.models.nul_free import NulFreeModel


class WebhookKind(StrEnum):
    SLACK = "slack"  # a Slack incoming webhook: a message with an Approve button
    JSON = "json"  # any HTTPS endpoint: a signed JSON body


class WebhookEvent(StrEnum):
    APPROVAL_REQUESTED = "approval.requested"
    TEST = "webhook.test"


class Webhook(NulFreeModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    tenant_id: str
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(repr=False, max_length=2000)  # a Slack URL is itself a secret
    kind: WebhookKind
    events: tuple[WebhookEvent, ...] = (WebhookEvent.APPROVAL_REQUESTED,)
    secret: str = Field(repr=False)  # signs JSON deliveries (HMAC-SHA256)
    enabled: bool = True
    created_at: int = Field(ge=0)
    created_by: str | None = None
    # What has been announced (``mandate.api.notify.Cursor``): anything past it is news.
    cursor: str = ""
    last_delivery_at: int | None = None
    last_ok: bool | None = None
    failures: int = Field(default=0, ge=0)  # deliveries failed in a row


class Delivery(NulFreeModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    webhook_id: str
    event: WebhookEvent
    at: int = Field(ge=0)
    ok: bool
    attempts: int = Field(ge=1)
    status: int | None = None  # the receiver's HTTP status, if it answered
    error: str | None = Field(default=None, max_length=300)
    duration_ms: float = Field(ge=0)
    subject: str | None = None  # the action it was about
