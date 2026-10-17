"""The policy decision point: a pure function from a snapshot to a decision outcome.

Rules implemented here: AUTH-001, AUTH-004, AUTH-005, AUTH-007 to AUTH-010, AUTH-015,
AUTH-017, AUTH-018, AUTH-022 (see docs/spec/authority-semantics.md). No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mandate.authority.candidates import (
    Candidate,
    CandidateStatus,
    Snapshot,
    candidate_status,
    superseded_ids,
)
from mandate.authority.precedence import pick_winner, precedence_key
from mandate.authority.scope import Applicability
from mandate.models.domain import (
    CheckRequest,
    Effect,
    IgnoredInstruction,
    LineageTrust,
    PathHop,
    Reason,
    Result,
)

REASON_NOTES: dict[Reason, str] = {
    Reason.AUTHORIZED: "A trusted rule allows this action.",
    Reason.CONFIRM_RULE: "A trusted rule requires the owner's confirmation first.",
    Reason.MIXED_LINEAGE: "The only matching rule has mixed origin, so confirmation is required.",
    Reason.EXPLICIT_DENY: "A rule denies this action.",
    Reason.AUTHORITY_REVOKED: "The rule that covered this action has been revoked.",
    Reason.CONSTRAINT_NOT_MET: "A rule covers this action but its limit is not met.",
    Reason.NO_AUTHORITY_PATH: "No active rule from the owner covers this action for this agent.",
    Reason.CHECK_ERROR: "The check failed, so the action is denied.",
}


@dataclass(frozen=True)
class PdpOutcome:
    result: Result
    reason: Reason
    winner: Candidate | None
    considered: tuple[Candidate, ...]
    ignored: tuple[IgnoredInstruction, ...]
    path: tuple[PathHop, ...]


class PolicyDecisionPoint(Protocol):
    """Strategy interface (ADR-012): the v1 implementation is ``DeterministicPDP``."""

    def decide(self, request: CheckRequest, snapshot: Snapshot, as_of: int) -> PdpOutcome: ...


def _key(candidate: Candidate) -> tuple[int, int, str]:
    activated = candidate.instruction.activated_at or 0
    return precedence_key(activated, candidate.instruction.effect, candidate.key)


def _winner_path(candidate: Candidate, agent_id: str) -> tuple[PathHop, ...]:
    mixed = candidate.lineage.trust is LineageTrust.MIXED
    hops: list[PathHop] = []
    trace = list(reversed(candidate.lineage.trace))  # utterance first, instruction last
    if trace and trace[0].principal_id:
        hops.append(PathHop(type="Principal", id=trace[0].principal_id))
    for node in trace:
        note = "mixed lineage" if mixed and node.label == "Instruction" else ""
        hops.append(PathHop(type=node.label, id=node.id, note=note))
    if not trace:
        hops.append(PathHop(type="Instruction", id=candidate.instruction.id))
    hops.append(PathHop(type="Scope", id=candidate.scope.scope_id))
    hops.extend(PathHop(type="Delegation", id=d.id) for d in candidate.chain)
    hops.append(PathHop(type="Agent", id=agent_id))
    return tuple(hops)


def _denial_path(
    agent_id: str, reason: Reason, relevant: list[Candidate], as_of: int
) -> tuple[PathHop, ...]:
    hops: list[PathHop] = [PathHop(type="Agent", id=agent_id)]
    for candidate in sorted(relevant, key=lambda c: c.key)[:5]:
        instruction = candidate.instruction
        if reason is Reason.AUTHORITY_REVOKED:
            when = instruction.revoked_at
            note = f"revoked at {when}" if when is not None else "delegation revoked"
        elif reason is Reason.CONSTRAINT_NOT_MET:
            note = f"limit max_amount={candidate.scope.max_amount} not met"
        else:
            note = ""
        hops.append(PathHop(type="Instruction", id=instruction.id, note=note))
    hops.append(PathHop(type="Note", id=reason.value, note=REASON_NOTES[reason]))
    return tuple(hops)


class DeterministicPDP:
    """Applies the authority rules to a snapshot. Deterministic and side-effect free."""

    def decide(self, request: CheckRequest, snapshot: Snapshot, as_of: int) -> PdpOutcome:
        superseded = superseded_ids(snapshot.supersessions, as_of)
        trusted_live: list[Candidate] = []
        mixed_live: list[Candidate] = []
        revoked: list[Candidate] = []
        constraint_failed: list[Candidate] = []
        ignored: dict[str, IgnoredInstruction] = {}

        for candidate in snapshot.candidates:
            status = candidate_status(candidate, as_of, superseded)
            if status is CandidateStatus.QUARANTINED:
                continue
            if candidate.lineage.trust is LineageTrust.UNTRUSTED:
                # AUTH-004 / AUTH-022: never contributes, never changes result, reason or path.
                ignored[candidate.instruction.id] = IgnoredInstruction(
                    id=candidate.instruction.id, why="untrusted_lineage"
                )
                continue
            if status is CandidateStatus.REVOKED:
                revoked.append(candidate)
            elif status is CandidateStatus.ACTIVE:
                if candidate.applicability is Applicability.CONSTRAINT_FAILED:
                    constraint_failed.append(candidate)
                elif candidate.lineage.trust is LineageTrust.TRUSTED:
                    trusted_live.append(candidate)
                else:
                    mixed_live.append(candidate)

        ignored_tuple = tuple(sorted(ignored.values(), key=lambda i: i.id))

        if trusted_live:
            winner = pick_winner(trusted_live, _key)
            assert winner is not None
            result, reason = {
                Effect.ALLOW: (Result.ALLOW, Reason.AUTHORIZED),
                Effect.CONFIRM: (Result.CONFIRM, Reason.CONFIRM_RULE),
                Effect.DENY: (Result.DENY, Reason.EXPLICIT_DENY),
            }[winner.instruction.effect]
            return PdpOutcome(
                result,
                reason,
                winner,
                tuple(trusted_live),
                ignored_tuple,
                _winner_path(winner, snapshot.agent_id),
            )

        if mixed_live:
            winner = pick_winner(mixed_live, _key)
            assert winner is not None
            if winner.instruction.effect is Effect.DENY:
                result, reason = Result.DENY, Reason.EXPLICIT_DENY
            else:
                result, reason = Result.CONFIRM, Reason.MIXED_LINEAGE
            return PdpOutcome(
                result,
                reason,
                winner,
                tuple(mixed_live),
                ignored_tuple,
                _winner_path(winner, snapshot.agent_id),
            )

        if revoked:
            reason = Reason.AUTHORITY_REVOKED
            relevant = revoked
        elif constraint_failed:
            reason = Reason.CONSTRAINT_NOT_MET
            relevant = constraint_failed
        else:
            reason = Reason.NO_AUTHORITY_PATH
            relevant = []
        return PdpOutcome(
            Result.DENY,
            reason,
            None,
            tuple(relevant),
            ignored_tuple,
            _denial_path(snapshot.agent_id, reason, relevant, as_of),
        )
