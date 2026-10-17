"""Human-readable explanations built from templates, never from a model.

A model cannot make an explanation wrong or be steered by injected text, because the
narrative is assembled only from the stored decision and its path.
"""

from __future__ import annotations

from dataclasses import dataclass

from mandate.authority.ports import RecordedDecision
from mandate.models.domain import Action, Decision, PathHop, Reason


@dataclass(frozen=True)
class Explanation:
    decision: Decision
    action: Action
    used: list[tuple[str, str]]  # (instruction id, role)
    narrative: str


def _first(path: list[PathHop], kind: str) -> PathHop | None:
    return next((hop for hop in path if hop.type == kind), None)


def narrate(recorded: RecordedDecision) -> str:
    decision, action = recorded.decision, recorded.action
    what = f"{action.action_type} on {action.resource}"
    rule = _first(decision.path, "Instruction")
    owner = _first(decision.path, "Principal")
    utterance = _first(decision.path, "Utterance")
    via = [hop.id for hop in decision.path if hop.type == "Delegation"]
    origin = (
        f" The rule {rule.id} comes from {'utterance ' + utterance.id if utterance else 'a source'}"
        f"{' by ' + owner.id if owner else ''}."
        if rule
        else ""
    )
    delegated = f" Authority reached the agent through delegation {', '.join(via)}." if via else ""
    ignored = (
        f" Ignored as untrusted: {', '.join(item.id for item in decision.ignored)}."
        if decision.ignored
        else ""
    )

    templates = {
        Reason.AUTHORIZED: f"Allowed: {what} is covered by an active rule.{origin}{delegated}",
        Reason.CONFIRM_RULE: (
            f"Needs approval: a rule requires the owner's confirmation for {what}."
            f"{origin}{delegated}"
        ),
        Reason.MIXED_LINEAGE: (
            f"Needs approval: the only matching rule for {what} has mixed origin.{origin}"
        ),
        Reason.EXPLICIT_DENY: f"Denied: a rule forbids {what}.{origin}{delegated}",
        Reason.AUTHORITY_REVOKED: f"Denied: the rule that covered {what} has been revoked.",
        Reason.CONSTRAINT_NOT_MET: f"Denied: a rule covers {what} but its limit is not met.",
        Reason.NO_AUTHORITY_PATH: (
            f"Denied: no active rule from the owner covers {what} for this agent."
        ),
        Reason.CHECK_ERROR: (
            f"Denied: the check could not be completed for {what}, so it was blocked."
        ),
    }
    return templates[decision.reason] + ignored


def explain(recorded: RecordedDecision) -> Explanation:
    return Explanation(
        decision=recorded.decision,
        action=recorded.action,
        used=[(u.instruction_id, u.role) for u in recorded.used],
        narrative=narrate(recorded),
    )
