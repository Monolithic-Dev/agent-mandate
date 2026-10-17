"""Notifications: tell the owner, through a webhook, that an action waits for them.

A background loop (``Notifier.run``) looks, every few seconds, at the tenants that have an
enabled webhook. Any action held for approval that is past the webhook's cursor is
announced, once, with a one-time approval link minted for the tenant's owner, and the cursor
moves past it. The cursor is a time plus the ids already covered at that exact millisecond,
because ids made in the same millisecond do not sort in the order they were made.
Because it reads the graph, it sees actions held by any process, the MCP
agent server included, and it survives a restart without repeating itself.

Deliveries:

* **Slack** (``kind: slack``): a message with the call, the agent, why it is held, and an
  Approve button that opens the link.
* **JSON** (``kind: json``): the facts as JSON, signed: ``X-Mandate-Signature: v1=<hex>``
  is HMAC-SHA256 over ``<X-Mandate-Timestamp>.<body>`` with the webhook's secret, so the
  receiver can check that it came from here and is fresh.

Each delivery is tried up to three times (on a network error, a 429 or a 5xx), never follows a
redirect, and is recorded with its outcome. A webhook URL must be HTTPS and must not resolve to
a private, loopback or link-local address (no server-side request forgery into the network
the API runs in); ``MANDATE_WEBHOOK_ALLOW_PRIVATE=true`` lifts that for local testing only.
The address is checked again at each delivery, not only when the webhook is saved.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from mandate.api.approval_links import mint_link
from mandate.api.tenancy import Runtimes, TenantRuntime
from mandate.authority.ports import StoredAction
from mandate.errors import MandateError, NotFound, ValidationFailure
from mandate.ids import MonotonicIds
from mandate.logging import get_logger
from mandate.models.accounts import Directory
from mandate.models.domain import ActionStatus, Role
from mandate.models.webhooks import Delivery, Webhook, WebhookEvent, WebhookKind

log = get_logger(__name__)

ATTEMPTS = 3
TIMEOUT_SECONDS = 5.0
KEEP_DELIVERIES = 50
PENDING_LOOKBACK = 50  # the newest held actions looked at per tenant per round
SIGNATURE_HEADER = "X-Mandate-Signature"


# --- where a webhook may point ---------------------------------------------------------


def _blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_url(url: str, *, allow_private: bool, resolve: bool = True) -> str:
    """The URL, if a webhook may post to it. Raises ``ValidationFailure`` otherwise."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValidationFailure("url: must be an https:// address")
    if parts.scheme == "http" and not allow_private:
        raise ValidationFailure("url: must be https://")
    if parts.username or parts.password:
        raise ValidationFailure("url: must not carry a username or password")
    if allow_private or not resolve:
        return url.strip()
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ValidationFailure("url: the host does not resolve") from None
    if not infos or any(_blocked(str(info[4][0])) for info in infos):
        raise ValidationFailure("url: must not point at a private or local address")
    return url.strip()


def mask_url(url: str) -> str:
    """Enough to recognise a webhook by, without revealing it (a Slack URL is a secret)."""
    parts = urlsplit(url)
    tail = url.rstrip("/")[-4:]
    return f"{parts.scheme}://{parts.hostname}/…{tail}"


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"v1={digest.hexdigest()}"


# --- sending ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SendResult:
    status: int | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status == 429 or self.status >= 500


class Sender(Protocol):
    def post(self, url: str, body: bytes, headers: dict[str, str]) -> SendResult: ...


class HttpSender:
    def __init__(self, *, allow_private: bool) -> None:
        self._allow_private = allow_private

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> SendResult:
        try:
            check_url(url, allow_private=self._allow_private)
        except ValidationFailure as error:
            return SendResult(None, error.message)
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
                response = client.post(url, content=body, headers=headers)
        except httpx.HTTPError as error:
            return SendResult(None, type(error).__name__)
        if not 200 <= response.status_code < 300:
            return SendResult(response.status_code, f"HTTP {response.status_code}")
        return SendResult(response.status_code, None)


# --- what is said ----------------------------------------------------------------------


@dataclass(frozen=True)
class Held:
    """A held action, with everything a message about it needs."""

    tenant_id: str
    action: StoredAction
    agent_name: str
    narrative: str | None
    approve_url: str | None
    console_url: str | None
    expires_at: int | None


def describe_call(stored: StoredAction) -> str:
    args = stored.action.args
    tool = args.get("tool")
    if isinstance(tool, str):
        tool_args = args.get("tool_args") if isinstance(args.get("tool_args"), dict) else {}
        shown = ", ".join(f"{k}={json.dumps(v)}" for k, v in (tool_args or {}).items())
        return f"{tool}({shown})"
    amount = f" ${args['amount']}" if "amount" in args else ""
    return f"{stored.action.action_type} {stored.action.resource}{amount}"


def json_body(event: WebhookEvent, delivery_id: str, at: int, held: Held | None) -> dict[str, Any]:
    body: dict[str, Any] = {"event": event.value, "delivery_id": delivery_id, "at": at}
    if held is not None:
        action = held.action.action
        body.update(
            {
                "tenant_id": held.tenant_id,
                "action": {
                    "id": action.id,
                    "action_type": action.action_type,
                    "resource": action.resource,
                    "args": action.args,
                    "call": describe_call(held.action),
                },
                "agent": {"id": held.action.agent_id, "name": held.agent_name},
                "decision_id": held.action.decision_id,
                "why_held": held.narrative,
                "approve_url": held.approve_url,
                "approve_url_expires_at": held.expires_at,
                "console_url": held.console_url,
            }
        )
    return body


def slack_body(event: WebhookEvent, held: Held | None, tenant_id: str) -> dict[str, Any]:
    if held is None:
        text = f"Agent Mandate: this webhook works. Approvals for `{tenant_id}` will appear here."
        return {"text": text}
    call = describe_call(held.action)
    text = f"{held.agent_name} wants to run `{call}` in {held.tenant_id} and is waiting for you."
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f":raised_hand: *{text}*"}},
    ]
    if held.narrative:
        why = {"type": "mrkdwn", "text": held.narrative[:2900]}
        blocks.append({"type": "context", "elements": [why]})
    buttons: list[dict[str, Any]] = []
    if held.approve_url:
        approve = {"type": "plain_text", "text": "Review and approve"}
        buttons.append({"type": "button", "text": approve, "url": held.approve_url,
                        "style": "primary"})  # fmt: skip
    if held.console_url:
        console = {"type": "plain_text", "text": "Open the console"}
        buttons.append({"type": "button", "text": console, "url": held.console_url})
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})
    return {"text": text, "blocks": blocks}


# --- the cursor ------------------------------------------------------------------------


@dataclass(frozen=True)
class Cursor:
    """Everything held up to ``at`` has been covered, and so have ``ids`` held at ``at``."""

    at: int = -1
    ids: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, text: str) -> Cursor:
        if not text or "|" not in text:
            return cls()
        at, _, ids = text.partition("|")
        try:
            return cls(int(at), frozenset(i for i in ids.split(",") if i))
        except ValueError:
            return cls()

    def __str__(self) -> str:
        return f"{self.at}|{','.join(sorted(self.ids))}"

    def covers(self, stored: StoredAction) -> bool:
        at = stored.action.at
        return at < self.at or (at == self.at and stored.action.id in self.ids)

    def advance(self, stored: StoredAction) -> Cursor:
        at = stored.action.at
        if at > self.at:
            return Cursor(at, frozenset({stored.action.id}))
        if at == self.at:
            return Cursor(at, self.ids | {stored.action.id})
        return self

    @classmethod
    def after(cls, held: list[StoredAction]) -> Cursor:
        """Past everything in ``held``: where a new (or re-enabled) webhook starts."""
        cursor = cls()
        for stored in held:
            cursor = cursor.advance(stored)
        return cursor


# --- the loop --------------------------------------------------------------------------


class Notifier:
    def __init__(
        self,
        runtimes: Runtimes,
        *,
        link_secret: str,
        public_url: str | None,
        link_ttl_seconds: int,
        sender: Sender,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._runtimes = runtimes
        self._link_secret = link_secret
        self._public_url = public_url.rstrip("/") if public_url else None
        self._link_ttl = link_ttl_seconds
        self._sender = sender
        self._sleep = sleep
        self._stop = threading.Event()
        self._delivery_ids = MonotonicIds("dlv")

    @property
    def directory(self) -> Directory:
        return self._runtimes.backend.directory

    def _now(self) -> int:
        return int(self._runtimes.clock.now_ms())

    def _held(self, runtime: TenantRuntime, stored: StoredAction) -> Held:
        tenant_id = runtime.tenant.id
        try:
            agent_name = runtime.store.get_agent(stored.agent_id).name
        except NotFound:
            agent_name = "An agent"
        narrative = None
        if stored.decision_id:
            try:
                narrative = runtime.service.explain(stored.decision_id).narrative
            except MandateError:
                narrative = None
        owner = next((p for p in runtime.store.list_principals() if p.role is Role.OWNER), None)
        approve_url = console_url = None
        expires_at = None
        if self._public_url:
            console_url = f"{self._public_url}/tenants/{tenant_id}?tab=approvals"
            if owner is not None:
                token, link = mint_link(
                    self._link_secret, tenant_id, stored.action.id, owner.id,
                    ttl_seconds=self._link_ttl,
                )  # fmt: skip
                approve_url = f"{self._public_url}/approve#{token}"
                expires_at = link.expires_at
        return Held(tenant_id, stored, agent_name, narrative, approve_url, console_url, expires_at)

    def deliver(self, webhook: Webhook, event: WebhookEvent, held: Held | None) -> Delivery:
        """Send one message (with retries) and record how it went."""
        at = self._now()
        delivery_id = self._delivery_ids.next(at)
        if webhook.kind is WebhookKind.SLACK:
            payload = slack_body(event, held, webhook.tenant_id)
        else:
            payload = json_body(event, delivery_id, at, held)
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        timestamp = str(at // 1000)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentMandate-Webhooks/1",
            "X-Mandate-Event": event.value,
            "X-Mandate-Delivery": delivery_id,
            "X-Mandate-Timestamp": timestamp,
            SIGNATURE_HEADER: sign(webhook.secret, timestamp, body),
        }
        began = time.perf_counter()
        result = SendResult(None, "not sent")
        attempts = 0
        for attempts in range(1, ATTEMPTS + 1):  # noqa: B007 - the count is recorded
            result = self._sender.post(webhook.url, body, headers)
            if result.ok or not result.retryable:
                break
            if attempts < ATTEMPTS:
                self._sleep(0.5 * attempts)
        delivery = Delivery(
            id=delivery_id,
            webhook_id=webhook.id,
            event=event,
            at=at,
            ok=result.ok,
            attempts=attempts,
            status=result.status,
            error=None if result.ok else (result.error or "failed")[:300],
            duration_ms=round((time.perf_counter() - began) * 1000, 1),
            subject=held.action.action.id if held else None,
        )
        self.directory.record_delivery(delivery, KEEP_DELIVERIES)
        return delivery

    def tick(self) -> int:
        """One round over every enabled webhook. Returns how many messages were sent."""
        sent = 0
        hooks = self.directory.list_webhooks(enabled=True)
        by_tenant: dict[str, list[Webhook]] = {}
        for hook in hooks:
            if WebhookEvent.APPROVAL_REQUESTED in hook.events:
                by_tenant.setdefault(hook.tenant_id, []).append(hook)
        for tenant_id, tenant_hooks in by_tenant.items():
            try:
                runtime = self._runtimes.require(tenant_id)
                pending = runtime.store.list_actions(
                    status=ActionStatus.PENDING, limit=PENDING_LOOKBACK
                )
            except MandateError as error:
                log.warning("notify_tenant_skipped", tenant=tenant_id, code=error.code)
                continue
            oldest_first = sorted(pending, key=lambda s: (s.action.at, s.action.id))
            held_cache: dict[str, Held] = {}
            for hook in tenant_hooks:
                start = Cursor.parse(hook.cursor)
                news = [s for s in oldest_first if not start.covers(s)]
                if not news:
                    continue
                cursor, last_ok, failures = start, hook.last_ok, hook.failures
                for stored in news:
                    held = held_cache.get(stored.action.id)
                    if held is None:
                        held = held_cache[stored.action.id] = self._held(runtime, stored)
                    delivery = self.deliver(hook, WebhookEvent.APPROVAL_REQUESTED, held)
                    sent += 1
                    cursor = cursor.advance(stored)  # announced once, delivered or not
                    last_ok = delivery.ok
                    failures = 0 if delivery.ok else failures + 1
                self.directory.record_progress(
                    hook.id, cursor=str(cursor), at=self._now(), ok=last_ok, failures=failures
                )
        return sent

    def start_cursor(self, tenant_id: str) -> str:
        """Where a new webhook starts: after everything already held."""
        runtime = self._runtimes.require(tenant_id)
        pending = runtime.store.list_actions(status=ActionStatus.PENDING, limit=PENDING_LOOKBACK)
        return str(Cursor.after(pending))

    def run(self, interval_seconds: float) -> None:
        """Loop until ``stop``; a failing round is logged, never fatal."""
        while not self._stop.wait(interval_seconds):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must outlive a bad round
                log.exception("notify_round_failed")

    def stop(self) -> None:
        self._stop.set()
