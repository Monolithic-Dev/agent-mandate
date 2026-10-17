"""The guarded call: the one code path between an agent's tool call and its effect.

Flow (docs/architecture.md section 5): validate arguments, derive the action and resource,
ask the authority engine, and only then touch the sandbox. Any problem along the way ends
in a refusal, never in an unchecked execution. Agents cannot influence the action type,
the resource or the decision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from mandate.authority.service import AuthorityService
from mandate.errors import MandateError
from mandate.gateway.sandbox.state import Sandbox
from mandate.gateway.tools import TOOLS, ToolSpec
from mandate.logging import get_logger
from mandate.models.domain import ActionStatus, Channel, CheckRequest, Result
from mandate.observability import metrics

log = get_logger(__name__)

Status = Literal["ok", "confirmation_required", "denied", "error"]


@dataclass(frozen=True)
class ToolResult:
    status: Status
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    decision_id: str | None = None
    approval_id: str | None = None  # the held action's id, for confirmation_required
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        for key in ("reason", "decision_id", "approval_id", "message"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.data:
            payload["data"] = self.data
        return payload


@dataclass
class GatewayRuntime:
    """Everything the guard needs for one tenant."""

    service: AuthorityService
    sandbox: Sandbox
    # Speaker used to record text that tools return (email bodies) as untrusted content.
    content_principal_id: str | None = None


def guarded_call(
    runtime: GatewayRuntime,
    agent_id: str,
    tool_name: str,
    raw_args: dict[str, Any],
    *,
    request_id: str | None = None,
) -> ToolResult:
    spec = TOOLS.get(tool_name)
    if spec is None:
        return ToolResult("error", message=f"unknown tool: {tool_name!r}")
    try:
        args = spec.model.model_validate(raw_args)
        resource = spec.resource(args, runtime.sandbox)
        request = CheckRequest(
            agent_id=agent_id,
            action_type=spec.action_type,
            resource=resource,
            args={**spec.check_args(args), "tool": tool_name, "tool_args": args.model_dump()},
        )
    except (ValidationError, ValueError, MandateError) as error:
        # Bad arguments never reach the engine or the sandbox.
        return _counted(
            tool_name, ToolResult("denied", reason="bad_arguments", message=_short(error))
        )

    began = time.perf_counter()
    checked = runtime.service.check(request, request_id=request_id)
    decision = checked.decision
    metrics.DECISION_SECONDS.labels("gateway").observe(time.perf_counter() - began)
    metrics.DECISIONS.labels(decision.result.value, decision.reason.value, "gateway").inc()
    if decision.result is Result.ALLOW:
        return _counted(tool_name, _execute(runtime, spec, args, checked.action.id, decision.id))
    if decision.result is Result.CONFIRM:
        return _counted(
            tool_name,
            ToolResult(
                "confirmation_required",
                reason=decision.reason.value,
                decision_id=decision.id,
                approval_id=checked.action.id,
            ),
        )
    return _counted(
        tool_name, ToolResult("denied", reason=decision.reason.value, decision_id=decision.id)
    )


def _counted(tool_name: str, result: ToolResult) -> ToolResult:
    metrics.TOOL_CALLS.labels(tool_name, result.status).inc()
    return result


def resolve_pending(
    runtime: GatewayRuntime, action_id: str, by_principal_id: str, *, approved: bool
) -> ToolResult:
    """The owner approves or declines an action that was held for confirmation.

    Raises ``NotOwner``, ``NotFound`` or ``Conflict`` (already resolved) as appropriate.
    """
    stored = runtime.service.resolve_action(action_id, by_principal_id, approved=approved)
    if not approved:
        return ToolResult("denied", reason="owner_declined", approval_id=action_id)
    spec = TOOLS.get(str(stored.action.args.get("tool")))
    if spec is None:
        runtime.service.mark_action(action_id, ActionStatus.DENIED)
        return ToolResult("error", message="the held action has no runnable tool")
    try:
        args = spec.model.model_validate(stored.action.args.get("tool_args", {}))
    except ValidationError as error:
        runtime.service.mark_action(action_id, ActionStatus.DENIED)
        return ToolResult("error", message=_short(error))
    return _execute(runtime, spec, args, action_id, None, already_marked=True)


def _execute(
    runtime: GatewayRuntime,
    spec: ToolSpec,
    args: Any,
    action_id: str,
    decision_id: str | None,
    *,
    already_marked: bool = False,
) -> ToolResult:
    try:
        data = spec.run(runtime.sandbox, args)
    except MandateError as error:
        _mark(runtime, action_id, ActionStatus.DENIED if already_marked else None)
        return ToolResult("error", message=error.message, decision_id=decision_id)
    except Exception:  # noqa: BLE001 - a failing tool must not crash the gateway
        log.exception("tool_failed", tool=spec.name)
        _mark(runtime, action_id, ActionStatus.DENIED if already_marked else None)
        return ToolResult("error", message="the tool failed", decision_id=decision_id)
    if not already_marked:
        _mark(runtime, action_id, ActionStatus.EXECUTED)
    if spec.name == "email_read":
        _record_untrusted(runtime, str(data.get("body", "")), f"email:{data.get('id')}")
    return ToolResult("ok", data=data, decision_id=decision_id)


def _mark(runtime: GatewayRuntime, action_id: str, status: ActionStatus | None) -> None:
    if status is None:
        return
    try:
        runtime.service.mark_action(action_id, status)
    except MandateError:
        log.exception("mark_action_failed", action_id=action_id)


def _record_untrusted(runtime: GatewayRuntime, text: str, source_ref: str) -> None:
    """Keep what a tool returned as untrusted content so it can be shown and audited."""
    if runtime.content_principal_id is None or not text.strip():
        return
    try:
        runtime.service.ingest_utterance(
            principal_id=runtime.content_principal_id,
            text=text[:4000],
            channel=Channel.UNTRUSTED_CONTENT,
            source_ref=source_ref,
        )
    except MandateError:
        log.exception("record_untrusted_failed", source_ref=source_ref)


def _short(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        return f"{location}: {first['msg']}" if location else str(first["msg"])
    return str(error)[:200]
