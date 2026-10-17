"""Replay: what would the decisions have been without this rule? (AUTH-027)

The tenant's data is cloned, the rule (and what derives from it) is quarantined on the
clone, and each affected decision is re-evaluated at its original time. The live data is
never modified and the clone is always removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mandate.authority.check import check_authority
from mandate.authority.ports import AuthorityStore
from mandate.clock import Clock
from mandate.lineage.blast_radius import blast_radius
from mandate.models.domain import CheckRequest, Reason, Result


@dataclass(frozen=True)
class ReplayChange:
    decision_id: str
    action_type: str
    resource: str
    was_result: Result
    was_reason: Reason
    now_result: Result
    now_reason: Reason


@dataclass(frozen=True)
class ReplayResult:
    instruction_id: str
    evaluated: int
    changes: list[ReplayChange] = field(default_factory=list)
    unchanged: int = 0


def replay_without(store: AuthorityStore, clock: Clock, instruction_id: str) -> ReplayResult:
    """Re-run every decision that used the instruction, as if it had never applied."""
    radius = blast_radius(store, instruction_id)
    affected = store.decisions_using(radius.instruction_ids)
    changes: list[ReplayChange] = []
    with store.clone_for_replay() as clone:
        clone.set_quarantined(radius.instruction_ids, True)
        for row in affected:
            args = {k: v for k, v in row.action.args.items() if k == "amount"}
            request = CheckRequest(
                agent_id=row.agent_id,
                action_type=row.action.action_type,
                resource=row.action.resource,
                args=args,
                as_of=row.decision.as_of,
            )
            redone = check_authority(clone, None, request, clock=clock, persist=False).decision
            was = row.decision
            if (redone.result, redone.reason) != (was.result, was.reason):
                changes.append(
                    ReplayChange(
                        decision_id=was.id,
                        action_type=row.action.action_type,
                        resource=row.action.resource,
                        was_result=was.result,
                        was_reason=was.reason,
                        now_result=redone.result,
                        now_reason=redone.reason,
                    )
                )
    return ReplayResult(
        instruction_id=instruction_id,
        evaluated=len(affected),
        changes=changes,
        unchanged=len(affected) - len(changes),
    )
