"""Verify a stored explanation against the facts in the graph.

Explanations are built from the stored decision and its path, never from a model, but a path
is only data: a bug, a bad migration or a tampered record could make it say something the
graph does not support. This module re-derives each claim a path makes from the store, using
only the read ports, and reports which hold. It is the equivalent, for this system, of a
"claim checker": every id cited must exist, and every link must be real.

What is checked for a decision that relied on a rule (allow, confirm or an explicit deny):

* the agent in the path is the agent that proposed the action, and exists;
* exactly one rule is recorded as the winner, and the path names it;
* every rule named in the path was recorded as used, and exists;
* the winner's effect fits the result (allow, deny, confirm; a mixed-origin rule only asks);
* the winner was active when the decision was made (as of that moment, not now);
* its scope covers the action type and the resource, and any amount limit holds;
* its origin, recomputed from the graph, has the trust the decision needed, and the path's
  principal, utterances and summaries are really on that origin chain;
* every delegation named in the path is one real chain from an agent the rule applies to to
  the acting agent, and every hop of it was live at that moment.

For denials with no winning rule only the first three apply. A failure means the explanation
cannot be trusted as written; it says nothing about whether the decision itself was right
(replay and the conformance tests cover that).
"""

from __future__ import annotations

from dataclasses import dataclass

from mandate.authority.delegation import MAX_CHAIN_DEPTH, Liveness, chain_liveness
from mandate.authority.lineage import compute_lineage
from mandate.authority.ports import AuthorityStore, InstructionRecord, RecordedDecision
from mandate.errors import MandateError
from mandate.models.domain import Effect, LineageTrust, PathHop, Reason, Result
from mandate.models.registry import action_type_covers
from mandate.models.resources import resource_matches

RELIES_ON_A_RULE = {
    Reason.AUTHORIZED,
    Reason.CONFIRM_RULE,
    Reason.MIXED_LINEAGE,
    Reason.EXPLICIT_DENY,
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class Verification:
    decision_id: str
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.ok)


def verify_decision(store: AuthorityStore, decision_id: str) -> Verification:
    """Check every claim in the stored explanation of ``decision_id``. Raises ``NotFound``."""
    recorded = store.get_decision(decision_id)
    checks: list[Check] = []
    _verify_agent(store, recorded, checks)
    _verify_used(store, recorded, checks)
    if recorded.decision.reason in RELIES_ON_A_RULE:
        _verify_winner(store, recorded, checks)
    return Verification(decision_id, tuple(checks))


def _hops(recorded: RecordedDecision, kind: str) -> list[PathHop]:
    return [hop for hop in recorded.decision.path if hop.type == kind]


def _verify_agent(store: AuthorityStore, recorded: RecordedDecision, checks: list[Check]) -> None:
    agent_hops = _hops(recorded, "Agent")
    named = {hop.id for hop in agent_hops}
    checks.append(
        Check(
            "path names the acting agent",
            named == {recorded.agent_id},
            f"path {sorted(named)} vs proposer {recorded.agent_id!r}",
        )
    )
    try:
        store.get_agent(recorded.agent_id)
        checks.append(Check("acting agent exists", True))
    except MandateError:
        checks.append(Check("acting agent exists", False, recorded.agent_id))


def _verify_used(store: AuthorityStore, recorded: RecordedDecision, checks: list[Check]) -> None:
    used_ids = {item.instruction_id for item in recorded.used}
    in_path = {hop.id for hop in _hops(recorded, "Instruction")}
    missing = sorted(in_path - used_ids)
    checks.append(
        Check("every rule in the path was recorded as used", not missing, ", ".join(missing))
    )
    gone = []
    for instruction_id in sorted(used_ids | in_path):
        try:
            store.get_instruction(instruction_id)
        except MandateError:
            gone.append(instruction_id)
    checks.append(Check("every cited rule exists", not gone, ", ".join(gone)))


def _verify_winner(store: AuthorityStore, recorded: RecordedDecision, checks: list[Check]) -> None:
    decision = recorded.decision
    winners = [item.instruction_id for item in recorded.used if item.role == "winner"]
    if len(winners) != 1:
        checks.append(Check("exactly one winning rule", False, f"{len(winners)} recorded"))
        return
    winner_id = winners[0]
    checks.append(Check("exactly one winning rule", True, winner_id))
    path_rules = {hop.id for hop in _hops(recorded, "Instruction")}
    checks.append(Check("the path names the winning rule", winner_id in path_rules, winner_id))
    try:
        instruction = store.get_instruction(winner_id)
    except MandateError:
        return  # already reported as a missing rule
    records = [r for r in store.list_instructions() if r.instruction.id == winner_id]

    effect = instruction.effect
    expected = {
        Result.ALLOW: effect is Effect.ALLOW,
        Result.DENY: effect is Effect.DENY,
        Result.CONFIRM: effect is Effect.CONFIRM
        or (decision.reason is Reason.MIXED_LINEAGE and effect is Effect.ALLOW),
    }[decision.result]
    checks.append(
        Check(
            "the winner's effect fits the result",
            expected,
            f"{effect.value} rule, {decision.result.value} result",
        )
    )

    live = (
        instruction.activated_at is not None
        and instruction.activated_at <= decision.as_of
        and (instruction.revoked_at is None or instruction.revoked_at > decision.as_of)
    )
    checks.append(Check("the winner was active when the decision was made", live))

    if records:
        _verify_scope(records[0], recorded, checks)
    else:
        checks.append(Check("the winner has a scope", False, winner_id))

    _verify_lineage(store, recorded, winner_id, checks)
    _verify_delegations(store, recorded, {r.agent_id for r in records}, checks)


def _verify_scope(
    record: InstructionRecord, recorded: RecordedDecision, checks: list[Check]
) -> None:
    action, scope = recorded.action, record.scope
    checks.append(
        Check(
            "the scope covers the action type",
            action_type_covers(scope.action_type, action.action_type),
            f"{scope.action_type} vs {action.action_type}",
        )
    )
    checks.append(
        Check(
            "the scope covers the resource",
            resource_matches(scope.resource_pattern, action.resource),
            f"{scope.resource_pattern} vs {action.resource}",
        )
    )
    limit = scope.constraints.max_amount
    if limit is not None and recorded.decision.result is Result.ALLOW:
        amount = action.args.get("amount")
        within = (
            isinstance(amount, int | float) and not isinstance(amount, bool) and amount <= limit
        )
        checks.append(Check("the amount is within the limit", within, f"{amount} vs {limit}"))


def _verify_lineage(
    store: AuthorityStore, recorded: RecordedDecision, winner_id: str, checks: list[Check]
) -> None:
    decision = recorded.decision
    lineage = compute_lineage(store, winner_id)
    needed = LineageTrust.MIXED if decision.reason is Reason.MIXED_LINEAGE else LineageTrust.TRUSTED
    if decision.result is Result.DENY:
        needed_ok = lineage.trust is not LineageTrust.UNTRUSTED
        needed_text = "not untrusted"
    else:
        needed_ok = lineage.trust is needed
        needed_text = needed.value
    checks.append(
        Check(
            "the rule's origin has the trust the decision needed",
            needed_ok,
            f"recomputed {lineage.trust.value}, needed {needed_text}",
        )
    )
    on_chain = {node.id for node in lineage.trace}
    cited = {hop.id for hop in decision.path if hop.type in ("Utterance", "Summary")}
    stray = sorted(cited - on_chain)
    checks.append(
        Check(
            "the cited utterances and summaries are on the rule's origin chain",
            not stray,
            ", ".join(stray),
        )
    )
    speakers = {node.principal_id for node in lineage.trace if node.principal_id}
    principals = {hop.id for hop in _hops(recorded, "Principal")}
    checks.append(
        Check(
            "the cited speaker said the cited utterance",
            principals <= speakers,
            f"{sorted(principals)} vs {sorted(speakers)}",
        )
    )


def _verify_delegations(
    store: AuthorityStore, recorded: RecordedDecision, applies_to: set[str], checks: list[Check]
) -> None:
    named = [hop.id for hop in _hops(recorded, "Delegation")]
    if not named:
        checks.append(
            Check(
                "the rule applies directly to the acting agent",
                recorded.agent_id in applies_to,
                f"{recorded.agent_id} in {sorted(applies_to)}",
            )
        )
        return
    chains = store.delegation_chains(recorded.agent_id, recorded.decision.as_of, MAX_CHAIN_DEPTH)
    for chain in chains:
        if [hop.id for hop in chain.hops] == named:
            checks.append(Check("the delegations form one real chain to the acting agent", True))
            checks.append(
                Check(
                    "the chain starts at an agent the rule applies to",
                    chain.root_agent_id in applies_to,
                    f"{chain.root_agent_id} in {sorted(applies_to)}",
                )
            )
            live = chain_liveness(chain.hops, recorded.decision.as_of) is Liveness.ACTIVE
            checks.append(
                Check(
                    "every delegation was live when the decision was made",
                    live or recorded.decision.result is not Result.ALLOW,
                )
            )
            return
    checks.append(
        Check("the delegations form one real chain to the acting agent", False, str(named))
    )
