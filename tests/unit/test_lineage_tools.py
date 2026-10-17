"""Blast radius, quarantine and replay: scenario S4 and its variants (AUTH-027)."""

import pytest
from fakes.world import World

from mandate.authority.service import AuthorityService
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.errors import NotFound
from mandate.lineage.blast_radius import blast_radius, derived_closure, quarantine
from mandate.lineage.replay import replay_without
from mandate.models.domain import Effect, Reason, Result

REFUNDS = [("80", 1200), ("81", 2500), ("82", 4800), ("83", 300)]


def refund_world(w: World):  # type: ignore[no-untyped-def]
    """S4: a typo (5000 instead of 500) supersedes the right rule and authorises four refunds."""
    said_ok = w.store.say(w.owner, "limit 500", at=T0)
    ok = w.store.rule(said_ok, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, max_amount=500)
    said_bad = w.store.say(w.owner, "limit 5000", at=T0 + 100_000)
    mistake = w.store.rule(
        said_bad, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0 + 100_000, max_amount=5000
    )
    w.store.supersede(mistake, ok, at=T0 + 100_000)
    decisions = []
    for index, (order, amount) in enumerate(REFUNDS):
        checked = w.check(
            "refund.issue",
            f"order/{order}",
            {"amount": amount},
            as_of=T0 + 101_000 + index,
        )
        assert checked.decision.result is Result.ALLOW
        decisions.append(checked.decision.id)
    return ok, mistake, decisions


def test_s4_blast_radius_lists_every_affected_decision(w: World) -> None:
    ok, mistake, decisions = refund_world(w)
    radius = blast_radius(w.store, mistake.id)
    assert [d.decision_id for d in radius.decisions] == decisions
    assert {d.action_type for d in radius.decisions} == {"refund.issue"}
    assert radius.summaries == [] and radius.derived_instructions == []
    # The earlier, correct rule was superseded and never used.
    assert blast_radius(w.store, ok.id).decisions == []


def test_auth027_live_graph_unchanged(w: World) -> None:
    _ok, mistake, decisions = refund_world(w)
    before = w.store.get_instruction(mistake.id)
    result = replay_without(w.store, w.clock, mistake.id)
    assert result.evaluated == 4 and result.unchanged == 1
    assert {c.decision_id for c in result.changes} == set(decisions[:3])
    for change in result.changes:
        assert (change.was_result, change.now_result) == (Result.ALLOW, Result.DENY)
        assert change.now_reason is Reason.CONSTRAINT_NOT_MET
    # AUTH-027: the live graph is untouched, and no replayed decision was recorded.
    assert w.store.get_instruction(mistake.id) == before
    assert not w.store.get_instruction(mistake.id).quarantined
    assert len(w.store.recorded) == 4


def test_auth027_replay_equals_quarantined_check(w: World) -> None:
    _ok, mistake, _decisions = refund_world(w)
    replayed = replay_without(w.store, w.clock, mistake.id)
    w.store.quarantine(mistake)
    for change in replayed.changes:
        direct = w.check(
            "refund.issue",
            change.resource,
            {"amount": dict(REFUNDS)[change.resource.split("/")[1]]},
            as_of=T0 + 101_000,
            persist=False,
        ).decision
        assert (direct.result, direct.reason) == (change.now_result, change.now_reason)


def test_replay_of_an_unused_rule_changes_nothing(w: World) -> None:
    ok, _mistake, _decisions = refund_world(w)
    result = replay_without(w.store, w.clock, ok.id)
    assert (result.evaluated, result.changes, result.unchanged) == (0, [], 0)


def test_replay_where_a_deny_was_wrong(w: World) -> None:
    said = w.store.say(w.owner, "allow reads", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    said_bad = w.store.say(w.owner, "mistaken deny", at=T0 + 10)
    mistake = w.store.rule(said_bad, Effect.DENY, "email.read", agents=[w.main], at=T0 + 10)
    denied = w.check("email.read", as_of=T0 + 20)
    assert denied.decision.reason is Reason.EXPLICIT_DENY
    (change,) = replay_without(w.store, w.clock, mistake.id).changes
    assert (change.was_result, change.now_result) == (Result.DENY, Result.ALLOW)


# --- derivation ---------------------------------------------------------------------


def derived_world(w: World):  # type: ignore[no-untyped-def]
    """A rule whose summary was turned into a second rule, plus a delegation made on it."""
    said = w.store.say(w.owner, "allow deleting files", at=T0)
    root = w.store.rule(said, Effect.ALLOW, "file.delete", agents=[w.main], at=T0)
    summary = w.store.summarise(root.id, at=T0 + 1)
    child = w.store.rule(summary, Effect.ALLOW, "file.write", agents=[w.main], at=T0 + 2)
    grandsummary = w.store.summarise(child.id, at=T0 + 3)
    grandchild = w.store.rule(grandsummary, Effect.ALLOW, "file.read", agents=[w.main], at=T0 + 4)
    w.store.delegate(w.main, w.sub, "file.read", at=T0 + 5)
    return root, child, grandchild, summary, grandsummary


def test_derived_closure_follows_two_levels(w: World) -> None:
    root, child, grandchild, summary, grandsummary = derived_world(w)
    summaries, derived = derived_closure(w.store, root.id)
    assert summaries == sorted([summary.id, grandsummary.id])
    assert derived == sorted([child.id, grandchild.id])


def test_derived_closure_survives_a_cycle(w: World) -> None:
    root, _child, _grandchild, summary, _gs = derived_world(w)
    w.store.derived_from[summary.id].append(w.store.rules[root.id].instruction.id)  # no-op loop
    w.store.derived_from[summary.id].append(summary.id)  # summary derived from itself
    assert derived_closure(w.store, root.id)[0]  # terminates


def test_blast_radius_includes_derived_rules_and_their_decisions(w: World) -> None:
    root, child, grandchild, _s, _gs = derived_world(w)
    read = w.check("file.read", "files/notes.txt", as_of=T0 + 100)
    write = w.check("file.write", "files/notes.txt", as_of=T0 + 100)
    assert read.decision.result is Result.ALLOW and write.decision.result is Result.ALLOW
    radius = blast_radius(w.store, root.id)
    assert set(radius.derived_instructions) == {child.id, grandchild.id}
    assert {d.decision_id for d in radius.decisions} == {read.decision.id, write.decision.id}


def test_quarantine_covers_derived_rules_and_is_reversible(w: World) -> None:
    root, child, grandchild, _s, _gs = derived_world(w)
    assert w.check("file.read", "files/a", as_of=T0 + 100, persist=False).decision.result is (
        Result.ALLOW
    )
    changed = quarantine(w.store, root.id)
    assert set(changed) == {root.id, child.id, grandchild.id}
    assert all(w.store.get_instruction(i).quarantined for i in changed)
    assert w.check("file.read", "files/a", as_of=T0 + 100, persist=False).decision.result is (
        Result.DENY
    )
    quarantine(w.store, root.id, value=False)
    assert w.check("file.read", "files/a", as_of=T0 + 100, persist=False).decision.result is (
        Result.ALLOW
    )
    assert quarantine(w.store, root.id, value=False)  # idempotent


def test_unknown_instruction_is_not_found(w: World) -> None:
    ghost = "ins_" + "0" * 26
    with pytest.raises(NotFound):
        blast_radius(w.store, ghost)
    with pytest.raises(NotFound):
        quarantine(w.store, ghost)
    with pytest.raises(NotFound):
        replay_without(w.store, w.clock, ghost)


def test_blast_radius_through_the_service_flow(w: World) -> None:
    service = AuthorityService(w.store, w.clock)
    ingested = service.ingest_utterance(
        principal_id=w.owner.id,
        text="You may issue refunds up to $5000.",
        channel=__import__("mandate.models.domain", fromlist=["Channel"]).Channel.OWNER_DIRECT,
    )
    rule = ingested.instructions[0].instruction
    service.confirm_instruction(rule.id, w.owner.id)
    checked = w.check("refund.issue", "order/80", {"amount": 100})
    assert checked.decision.result is Result.ALLOW
    radius = blast_radius(w.store, rule.id)
    assert [d.decision_id for d in radius.decisions] == [checked.decision.id]
