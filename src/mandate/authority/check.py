"""``check_authority``: the use case behind every guarded tool call.

Fails closed (AUTH-019): any error, including a graph outage or a failure to write the
audit record, yields ``deny`` with reason ``check_error``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from mandate.authority.candidates import build_snapshot
from mandate.authority.pdp import REASON_NOTES, DeterministicPDP, PdpOutcome, PolicyDecisionPoint
from mandate.authority.ports import AuthorityReader, DecisionRecorder, UsedInstruction
from mandate.clock import Clock
from mandate.errors import GraphUnavailable
from mandate.ids import new_id
from mandate.logging import get_logger
from mandate.models.domain import (
    Action,
    ActionStatus,
    CheckRequest,
    Decision,
    IgnoredInstruction,
    PathHop,
    Reason,
    Result,
)

log = get_logger(__name__)

_ACTION_STATUS = {
    Result.ALLOW: ActionStatus.PROPOSED,
    Result.CONFIRM: ActionStatus.PENDING,
    Result.DENY: ActionStatus.DENIED,
}


@dataclass(frozen=True)
class CheckResult:
    decision: Decision
    action: Action
    outcome: PdpOutcome | None = None
    # Set when the decision is a fail-closed denial: "graph_unavailable", "internal" or
    # "persist_failed". Interfaces can map "graph_unavailable" to HTTP 503.
    error_kind: str | None = None


def _used(outcome: PdpOutcome) -> list[UsedInstruction]:
    used: list[UsedInstruction] = []
    seen: set[str] = set()
    if outcome.winner is not None:
        used.append(UsedInstruction(outcome.winner.instruction.id, "winner"))
        seen.add(outcome.winner.instruction.id)
    for candidate in outcome.considered:
        if candidate.instruction.id not in seen:
            used.append(UsedInstruction(candidate.instruction.id, "considered"))
            seen.add(candidate.instruction.id)
    return used


def check_authority(
    reader: AuthorityReader,
    recorder: DecisionRecorder | None,
    request: CheckRequest,
    *,
    clock: Clock,
    pdp: PolicyDecisionPoint | None = None,
    persist: bool = True,
    request_id: str | None = None,
    id_factory: Callable[[str], str] = new_id,
) -> CheckResult:
    """Decide whether ``request`` is authorised, and (unless ``persist`` is false) record it."""
    started = time.perf_counter()
    now = clock.now_ms()
    as_of = request.as_of if request.as_of is not None else now
    engine = pdp or DeterministicPDP()
    error_kind: str | None = None
    outcome: PdpOutcome | None
    ignored: list[IgnoredInstruction]

    try:
        snapshot = build_snapshot(reader, request, as_of)
        outcome = engine.decide(request, snapshot, as_of)
        result, reason, path = outcome.result, outcome.reason, list(outcome.path)
        ignored = list(outcome.ignored)
    except GraphUnavailable:
        error_kind, outcome, ignored = "graph_unavailable", None, []
        result, reason, path = Result.DENY, Reason.CHECK_ERROR, []
        log.error("check_failed", kind=error_kind, agent_id=request.agent_id)
    except Exception:  # noqa: BLE001 - the one deliberate broad catch: fail closed (ADR-011)
        error_kind, outcome, ignored = "internal", None, []
        result, reason, path = Result.DENY, Reason.CHECK_ERROR, []
        log.exception("check_failed", kind=error_kind, agent_id=request.agent_id)

    def build(
        res: Result, rsn: Reason, hops: list[PathHop], ign: list[IgnoredInstruction]
    ) -> CheckResult:
        if not hops:
            hops = [PathHop(type="Note", id=rsn.value, note=REASON_NOTES[rsn])]
        decision = Decision(
            id=id_factory("dec"),
            result=res,
            reason=rsn,
            as_of=as_of,
            at=now,
            path=hops,
            ignored=ign,
            latency_ms=(time.perf_counter() - started) * 1000,
            request_id=request_id,
        )
        action = Action(
            id=id_factory("act"),
            action_type=request.action_type,
            resource=request.resource,
            args=request.args,
            status=_ACTION_STATUS[res],
            at=now,
        )
        return CheckResult(decision, action, outcome, error_kind)

    checked = build(result, reason, path, ignored)

    if persist and recorder is not None:
        used = _used(outcome) if outcome is not None else []
        try:
            recorder.record_decision(checked.action, checked.decision, used, request.agent_id)
        except Exception:  # noqa: BLE001 - no audit record means no action (fail closed)
            log.exception("record_failed", agent_id=request.agent_id)
            error_kind = "persist_failed"
            outcome = None
            checked = build(Result.DENY, Reason.CHECK_ERROR, [], [])

    log.info(
        "check_decided",
        agent_id=request.agent_id,
        action_type=request.action_type,
        result=checked.decision.result.value,
        reason=checked.decision.reason.value,
        latency_ms=round(checked.decision.latency_ms, 3),
        error_kind=error_kind,
    )
    return checked
