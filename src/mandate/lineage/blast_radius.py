"""Blast radius and quarantine: what a rule touched, and switching it (and its offspring) off.

Quarantine only sets a flag. Nothing is deleted, so every past decision stays auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mandate.authority.ports import AuthorityStore
from mandate.models.domain import Reason, Result

MAX_DERIVATION_STEPS = 10


@dataclass(frozen=True)
class AffectedDecision:
    decision_id: str
    result: Result
    reason: Reason
    action_type: str
    resource: str
    agent_id: str
    at: int


@dataclass(frozen=True)
class BlastRadius:
    instruction_id: str
    summaries: list[str] = field(default_factory=list)
    derived_instructions: list[str] = field(default_factory=list)
    delegations: list[str] = field(default_factory=list)
    decisions: list[AffectedDecision] = field(default_factory=list)

    @property
    def instruction_ids(self) -> list[str]:
        """The instruction itself plus everything derived from it."""
        return [self.instruction_id, *self.derived_instructions]


def derived_closure(store: AuthorityStore, instruction_id: str) -> tuple[list[str], list[str]]:
    """Follow derivation to a fixpoint (bounded, cycle-safe).

    Returns (summaries, derived instruction ids), both excluding the starting instruction.
    """
    seen_instructions = {instruction_id}
    seen_summaries: set[str] = set()
    frontier = [instruction_id]
    for _ in range(MAX_DERIVATION_STEPS):
        summaries, derived = store.derivation_step(frontier)
        seen_summaries.update(summaries)
        fresh = [d for d in derived if d not in seen_instructions]
        if not fresh:
            break
        seen_instructions.update(fresh)
        frontier = fresh
    return sorted(seen_summaries), sorted(seen_instructions - {instruction_id})


def blast_radius(store: AuthorityStore, instruction_id: str) -> BlastRadius:
    """Everything an instruction affected. Raises ``NotFound`` for an unknown instruction."""
    store.get_instruction(instruction_id)
    summaries, derived = derived_closure(store, instruction_id)
    ids = [instruction_id, *derived]
    decisions = [
        AffectedDecision(
            decision_id=row.decision.id,
            result=row.decision.result,
            reason=row.decision.reason,
            action_type=row.action.action_type,
            resource=row.action.resource,
            agent_id=row.agent_id,
            at=row.decision.at,
        )
        for row in store.decisions_using(ids)
    ]
    return BlastRadius(
        instruction_id=instruction_id,
        summaries=summaries,
        derived_instructions=derived,
        delegations=store.delegations_via(ids),
        decisions=decisions,
    )


def quarantine(
    store: AuthorityStore,
    instruction_id: str,
    value: bool = True,
    *,
    at: int | None = None,
    by: str | None = None,
) -> list[str]:
    """Quarantine (or release) an instruction and everything derived from it.

    ``at`` and ``by`` record when and by whom on every changed instruction. Returns the
    instruction ids that were changed. Idempotent.
    """
    store.get_instruction(instruction_id)
    _summaries, derived = derived_closure(store, instruction_id)
    ids = [instruction_id, *derived]
    store.set_quarantined(ids, value, at=at, by=by)
    return ids
