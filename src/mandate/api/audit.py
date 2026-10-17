"""The audit trail: who changed what, when, through which route, and how it ended.

Every request that could change something (anything but GET, HEAD and OPTIONS) is recorded
once its response is ready, including refusals, so a denied attempt is as visible as a
success. Agents' tool calls and checks are not recorded here: each one is already a Decision
in the tenant's graph, with far more detail. Requests that never identified anyone (no key,
no session) are not recorded either; they would let anyone fill the trail with noise.

Routes that act for someone the middleware cannot see (a sign-in, an approval link) name
the actor themselves through ``set_actor``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from mandate.api.keys import Caller
from mandate.ids import MonotonicIds, new_id
from mandate.logging import get_logger
from mandate.models.accounts import ActorKind, AuditEvent, Outcome
from mandate.observability import metrics

log = get_logger(__name__)

T = "/v1/tenants/{tenant_id}"
RULE = f"{T}/instructions/{{instruction_id}}"

# Route template and method -> a stable action name. Anything missing still gets recorded,
# as "<method> <route>", so a new route is never silently left out.
ACTIONS: dict[tuple[str, str], str] = {
    ("POST", "/v1/tenants"): "tenant.create",
    ("DELETE", T): "tenant.delete",
    ("POST", f"{T}/principals"): "principal.create",
    ("POST", f"{T}/agents"): "agent.create",
    ("POST", f"{T}/utterances"): "owner.say",
    ("POST", f"{RULE}/confirm"): "rule.confirm",
    ("POST", f"{RULE}/revoke"): "rule.revoke",
    ("POST", f"{RULE}/quarantine"): "rule.quarantine",
    ("DELETE", f"{RULE}/quarantine"): "rule.release",
    ("POST", f"{RULE}/replay"): "rule.replay",
    ("POST", f"{T}/delegations"): "delegation.create",
    ("POST", f"{T}/delegations/{{delegation_id}}/revoke"): "delegation.revoke",
    ("POST", f"{T}/actions/{{action_id}}/approve"): "action.resolve",
    ("POST", f"{T}/actions/{{action_id}}/approval-link"): "approval_link.create",
    ("POST", "/v1/approval-links/resolve"): "action.resolve_by_link",
    ("POST", f"{T}/agents/{{agent_id}}/tokens"): "token.mint",
    ("POST", f"{T}/token-revocations"): "token.revoke",
    ("POST", "/v1/runs"): "scenario.run",
    ("POST", "/v1/demo/reset"): "demo.reset",
    ("POST", "/v1/auth/login"): "auth.login",
    ("POST", "/v1/auth/logout"): "auth.logout",
    ("POST", "/v1/auth/password"): "auth.password_change",
    ("POST", "/v1/auth/sessions/end"): "auth.sessions_end",
    ("DELETE", "/v1/auth/sessions/{session_id}"): "auth.session_end",
    ("POST", f"{T}/webhooks"): "webhook.create",
    ("PATCH", f"{T}/webhooks/{{webhook_id}}"): "webhook.update",
    ("DELETE", f"{T}/webhooks/{{webhook_id}}"): "webhook.delete",
    ("POST", f"{T}/webhooks/{{webhook_id}}/test"): "webhook.test",
    ("POST", "/v1/users"): "user.create",
    ("PATCH", "/v1/users/{user_id}"): "user.update",
    ("POST", "/v1/users/{user_id}/password"): "user.password_reset",
    ("POST", "/v1/users/{user_id}/sessions/end"): "user.sessions_end",
}

NOT_AUDITED = frozenset(
    {
        ("POST", f"{T}/tool-calls"),  # a Decision in the tenant graph already
        ("POST", f"{T}/check"),  # likewise
        ("POST", "/v1/approval-links/inspect"),  # a read that carries its token in the body
        ("POST", f"{T}/utterances/preview"),  # a read: nothing live changes
    }
)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TEXT_MAX = 120
TARGET_PARAMS = (
    "instruction_id",
    "action_id",
    "delegation_id",
    "agent_id",
    "user_id",
    "session_id",
    "webhook_id",
)


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: str | None
    name: str | None
    tenant_id: str | None = None
    target: str | None = None


def set_actor(request: Request, actor: Actor) -> None:
    """For routes whose caller is not an API key or session (sign-in, approval links)."""
    request.state.audit_actor = actor


def note_created(request: Request, target: str, *, tenant_id: str | None = None) -> None:
    """A route that creates something names it, since its id is not in the path."""
    request.state.audit_target = target
    if tenant_id is not None:
        request.state.audit_tenant = tenant_id


def clean(value: object) -> str | None:
    """Path values come from the caller: keep them printable and short, never NUL."""
    if value is None:
        return None
    text = "".join(ch if ch.isprintable() else "?" for ch in str(value))
    return text[:TEXT_MAX]


def action_name(method: str, route: str) -> str:
    return ACTIONS.get((method, route), f"{method.lower()} {route}")


def outcome_of(status: int) -> Outcome:
    if status < 400:
        return Outcome.SUCCESS
    if status in (401, 403, 429):
        return Outcome.DENIED
    return Outcome.FAILED


def event_for(
    request: Request, status: int, now_ms: int, ids: MonotonicIds | None = None
) -> AuditEvent | None:
    """The event for a finished request, or None if it is not one we record."""
    method = request.method
    route = getattr(request.scope.get("route"), "path", None)
    if method in SAFE_METHODS or route is None or (method, route) in NOT_AUDITED:
        return None
    actor: Actor | None = getattr(request.state, "audit_actor", None)
    caller: Caller | None = getattr(request.state, "caller", None)
    if actor is None and caller is not None:
        actor = Actor(ActorKind(caller.kind), caller.id, caller.name)
    if actor is None:
        return None
    params = request.scope.get("path_params") or {}
    target = (
        actor.target
        or getattr(request.state, "audit_target", None)
        or next((params[p] for p in TARGET_PARAMS if p in params), None)
    )
    tenant_id = (
        actor.tenant_id or params.get("tenant_id") or getattr(request.state, "audit_tenant", None)
    )
    return AuditEvent(
        id=ids.next(now_ms) if ids else new_id("aud", now_ms=now_ms),
        at=now_ms,
        actor_kind=actor.kind,
        actor_id=actor.id,
        actor_name=clean(actor.name),
        action=action_name(method, route),
        method=method,
        route=route,
        tenant_id=clean(tenant_id),
        target=clean(target),
        status=status,
        outcome=outcome_of(status),
        request_id=getattr(request.state, "request_id", None),
    )


class AuditMiddleware(BaseHTTPMiddleware):
    """Records the audit event after the route has answered.

    A failed audit write is logged and counted but does not turn a completed change into an
    error: the change already happened, and an error would invite a retry that repeats it.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._ids = MonotonicIds("aud")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        runtimes = request.app.state.runtimes
        try:
            event = event_for(request, response.status_code, runtimes.clock.now_ms(), self._ids)
            if event is not None:
                await run_in_threadpool(runtimes.backend.directory.record_audit, event)
        except Exception:  # noqa: BLE001 - the response is final; auditing must not change it
            metrics.AUDIT_WRITE_FAILURES.inc()
            log.exception(
                "audit_write_failed", request_id=getattr(request.state, "request_id", None)
            )
        return response
