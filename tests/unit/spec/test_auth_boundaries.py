"""Boundary and detail tests added after mutation testing showed they were unguarded.

Each test pins one behaviour that a one-token edit to the engine used to leave undetected
(see scripts/mutation_test.py and docs/results/ for the run that found the gap).
"""

import dataclasses
import importlib
from typing import Any

import pytest
from fakes.world import World

from mandate.authority import candidates, check, lineage, pdp, scope
from mandate.authority.candidates import superseded_ids
from mandate.authority.delegation import is_well_formed
from mandate.authority.lineage import compute_lineage
from mandate.authority.ports import DelegationChain, Supersession
from mandate.authority.scope import _amount_within
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.models.domain import AgentKind, Channel, Effect, Reason, Result


def hop_types(path: Any) -> list[str]:
    return [hop.type for hop in path]


# --- decisions are immutable values --------------------------------------------------


@pytest.mark.parametrize("module", [candidates, check, lineage, pdp, scope])
def test_every_engine_dataclass_is_frozen(module: Any) -> None:
    module = importlib.import_module(module.__name__)
    classes = [
        c
        for c in vars(module).values()
        if isinstance(c, type) and dataclasses.is_dataclass(c) and c.__module__ == module.__name__
    ]
    assert classes
    assert all(c.__dataclass_params__.frozen for c in classes), module.__name__


# --- supersession and amount boundaries ---------------------------------------------


def test_supersession_takes_effect_at_exactly_its_timestamp() -> None:
    record = Supersession(superseded_id="ins_a", by_id="ins_b", at=100, by_quarantined=False)
    assert superseded_ids([record], 99) == frozenset()
    assert superseded_ids([record], 100) == frozenset({"ins_a"})


def test_a_zero_amount_is_within_a_limit_and_negative_is_not() -> None:
    assert _amount_within(0, 0) and _amount_within(0, 500)
    assert _amount_within(500, 500) and not _amount_within(501, 500)
    assert not _amount_within(-1, 500)


# --- delegation chain shape ----------------------------------------------------------


def make_chain(w: World, length: int, *, close_loop: bool = False) -> tuple[Any, ...]:
    agents = [w.main] + [w.store.add_agent(f"a{i}", AgentKind.SUB) for i in range(length)]
    hops = [w.store.delegate(agents[i], agents[i + 1], "email.read", at=T0) for i in range(length)]
    if close_loop:
        hops.append(w.store.delegate(agents[length], agents[0], "email.read", at=T0))
    return agents[0], agents[-1], tuple(hops)


def test_chain_depth_boundary(w: World) -> None:
    root, target, hops = make_chain(w, 4)  # literal on purpose: the limit is ADR-pinned
    assert is_well_formed(DelegationChain(root.id, hops), target.id)
    root, target, hops = make_chain(w, 5)
    assert not is_well_formed(DelegationChain(root.id, hops), target.id)


def test_malformed_chains_are_rejected(w: World) -> None:
    root, target, hops = make_chain(w, 2)
    assert is_well_formed(DelegationChain(root.id, hops), target.id)
    assert not is_well_formed(DelegationChain(root.id, ()), target.id)
    assert not is_well_formed(DelegationChain(target.id, hops), target.id)  # wrong root
    assert not is_well_formed(DelegationChain(root.id, hops), root.id)  # wrong target
    assert not is_well_formed(DelegationChain(root.id, hops[::-1]), target.id)  # not contiguous
    assert not is_well_formed(DelegationChain(root.id, hops[:1]), target.id)  # stops short
    b, c, d = (w.store.add_agent(n, AgentKind.SUB) for n in "bcd")
    gap = (
        w.store.delegate(w.main, b, "email.read", at=T0),
        w.store.delegate(c, d, "email.read", at=T0),
    )
    assert not is_well_formed(DelegationChain(w.main.id, gap), d.id)  # b never hands on to c


def test_a_chain_that_returns_to_an_earlier_agent_is_rejected(w: World) -> None:
    root, _, hops = make_chain(w, 2, close_loop=True)
    assert not is_well_formed(DelegationChain(root.id, hops), root.id)


# --- explanation paths ---------------------------------------------------------------


def test_allow_path_runs_from_the_person_to_the_agent(w: World) -> None:
    said = w.store.say(w.owner, "allow reads", at=T0)
    rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    path = w.check("email.read", as_of=T0 + 1, persist=False).decision.path
    assert hop_types(path) == ["Principal", "Utterance", "Instruction", "Scope", "Agent"]
    assert [h.id for h in path][0] == w.owner.id and path[2].id == rule.id
    assert all(h.note == "" for h in path)


def test_mixed_lineage_marks_the_instruction_hop(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(owner_utt.id, email.id, at=T0)
    w.store.rule(blended, Effect.ALLOW, "email.delete", agents=[w.main], at=T0)
    decision = w.check("email.delete", as_of=T0 + 1, persist=False).decision
    assert decision.reason is Reason.MIXED_LINEAGE
    notes = {h.type: h.note for h in decision.path}
    assert notes["Instruction"] == "mixed lineage"
    assert notes["Utterance"] == ""


def test_delegated_path_lists_each_delegation(w: World) -> None:
    said = w.store.say(w.owner, "allow reads", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    delegation = w.store.delegate(w.main, w.sub, "email.read", at=T0)
    path = w.check("email.read", agent=w.sub, as_of=T0 + 1, persist=False).decision.path
    assert hop_types(path)[-3:] == ["Scope", "Delegation", "Agent"]
    assert path[-2].id == delegation.id


def test_revoked_denial_names_when_the_rule_was_revoked(w: World) -> None:
    said = w.store.say(w.owner, "allow reads", at=T0)
    rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    w.store.revoke(rule, at=T0 + 20)
    decision = w.check("email.read", as_of=T0 + 30, persist=False).decision
    assert decision.reason is Reason.AUTHORITY_REVOKED
    assert [h.note for h in decision.path if h.type == "Instruction"] == [f"revoked at {T0 + 20}"]


def test_constraint_denial_states_the_limit(w: World) -> None:
    said = w.store.say(w.owner, "refunds up to 500", at=T0)
    w.store.rule(said, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, max_amount=500)
    decision = w.check(
        "refund.issue", "order/1", {"amount": 900}, as_of=T0 + 1, persist=False
    ).decision
    assert decision.reason is Reason.CONSTRAINT_NOT_MET
    assert "max_amount=500" in decision.path[1].note


def test_denial_path_lists_at_most_five_instructions(w: World) -> None:
    for i in range(7):
        said = w.store.say(w.owner, f"allow {i}", at=T0 + i)
        rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0 + i)
        w.store.revoke(rule, at=T0 + 100 + i)
    decision = w.check("email.read", as_of=T0 + 200, persist=False).decision
    assert decision.reason is Reason.AUTHORITY_REVOKED
    assert hop_types(decision.path).count("Instruction") == 5
    assert decision.result is Result.DENY


# --- lineage -------------------------------------------------------------------------


def summary_chain(w: World, levels: int) -> str:
    """An instruction whose origin sits behind ``levels`` summary-of-instruction steps."""
    said = w.store.say(w.owner, "allow reads", at=T0)
    current = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    for _ in range(levels):
        summary = w.store.summarise(current.id, at=T0)
        current = w.store.rule(summary, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    return current.id


def test_lineage_search_stops_six_hops_from_the_instruction(w: World) -> None:
    reachable = compute_lineage(w.store, summary_chain(w, 2))  # utterance five hops away
    assert reachable.trust.value == "trusted"
    too_deep = compute_lineage(w.store, summary_chain(w, 3))  # seven hops away
    assert too_deep.trust.value == "untrusted"


def test_the_trace_follows_a_trusted_origin_even_when_listed_after_an_untrusted_one(
    w: World,
) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(email.id, owner_utt.id, at=T0)
    rule = w.store.rule(blended, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    result = compute_lineage(w.store, rule.id)
    assert result.trace[-1].id == owner_utt.id
    only_untrusted = w.store.rule(email, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert compute_lineage(w.store, only_untrusted.id).trace[-1].id == email.id
