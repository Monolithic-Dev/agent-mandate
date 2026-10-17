"""Conformance tests for AUTH-017 to AUTH-021 and AUTH-025."""

import pytest
from fakes.world import World

from mandate.clock import SCENARIO_T0_MS as T0
from mandate.errors import GraphUnavailable
from mandate.models.domain import ActionStatus, Channel, Effect, Reason, Result


def rule(w: World, effect: Effect, action: str = "email.delete", *, at: int = T0, **kw):  # type: ignore[no-untyped-def]
    said = w.store.say(w.owner, "rule", at=at)
    return w.store.rule(said, effect, action, agents=[w.main], at=at, **kw)


def decide(w: World, action: str = "email.delete", as_of: int = T0 + 1000):  # type: ignore[no-untyped-def]
    return w.check(action, as_of=as_of, persist=False).decision


def test_auth017_recency_and_tie_break(w: World) -> None:
    rule(w, Effect.DENY, at=T0)
    rule(w, Effect.ALLOW, at=T0 + 10)
    assert decide(w).result is Result.ALLOW  # most recent wins
    rule(w, Effect.CONFIRM, at=T0 + 10)  # tie with the allow: confirm beats allow
    assert decide(w).result is Result.CONFIRM
    rule(w, Effect.DENY, at=T0 + 10)  # tie with both: deny beats all
    assert decide(w).result is Result.DENY


def test_auth018_reason_table_allow(w: World) -> None:
    rule(w, Effect.ALLOW)
    d = decide(w)
    assert (d.result, d.reason) == (Result.ALLOW, Reason.AUTHORIZED)


def test_auth018_reason_table_confirm_rule(w: World) -> None:
    rule(w, Effect.CONFIRM)
    d = decide(w)
    assert (d.result, d.reason) == (Result.CONFIRM, Reason.CONFIRM_RULE)


def test_auth018_reason_table_mixed_lineage(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(owner_utt.id, email.id, at=T0)
    w.store.rule(blended, Effect.ALLOW, "email.delete", agents=[w.main], at=T0)
    d = decide(w)
    assert (d.result, d.reason) == (Result.CONFIRM, Reason.MIXED_LINEAGE)


def test_auth018_reason_table_explicit_deny(w: World) -> None:
    rule(w, Effect.DENY)
    d = decide(w)
    assert (d.result, d.reason) == (Result.DENY, Reason.EXPLICIT_DENY)


def test_auth018_reason_table_authority_revoked(w: World) -> None:
    w.store.revoke(rule(w, Effect.ALLOW), at=T0 + 5)
    d = decide(w)
    assert (d.result, d.reason) == (Result.DENY, Reason.AUTHORITY_REVOKED)


def test_auth018_reason_table_constraint_not_met(w: World) -> None:
    rule(w, Effect.ALLOW, "refund.issue", max_amount=10)
    d = w.check("refund.issue", "order/1", {"amount": 99}, as_of=T0 + 1, persist=False).decision
    assert (d.result, d.reason) == (Result.DENY, Reason.CONSTRAINT_NOT_MET)


def test_auth018_reason_table_no_authority_path(w: World) -> None:
    d = decide(w)
    assert (d.result, d.reason) == (Result.DENY, Reason.NO_AUTHORITY_PATH)


def test_auth018_revoked_is_reported_before_constraint(w: World) -> None:
    revoked = rule(w, Effect.ALLOW, "refund.issue", max_amount=500)
    w.store.revoke(revoked, at=T0 + 5)
    rule(w, Effect.ALLOW, "refund.issue", at=T0 + 1, max_amount=10)
    d = w.check("refund.issue", "order/1", {"amount": 99}, as_of=T0 + 100, persist=False).decision
    assert d.reason is Reason.AUTHORITY_REVOKED


def test_auth019_graph_failure_denies(w: World) -> None:
    rule(w, Effect.ALLOW)
    w.store.fail_reads = GraphUnavailable("down")
    checked = w.check("email.delete", as_of=T0 + 10)
    assert (checked.decision.result, checked.decision.reason) == (Result.DENY, Reason.CHECK_ERROR)
    assert checked.error_kind == "graph_unavailable"


def test_auth019_internal_error_denies(w: World) -> None:
    rule(w, Effect.ALLOW)
    w.store.fail_reads = RuntimeError("boom")
    checked = w.check("email.delete", as_of=T0 + 10)
    assert (checked.decision.result, checked.decision.reason) == (Result.DENY, Reason.CHECK_ERROR)
    assert checked.error_kind == "internal"
    assert checked.action.status is ActionStatus.DENIED


def test_auth019_failure_to_record_denies(w: World) -> None:
    rule(w, Effect.ALLOW)
    w.store.fail_record = RuntimeError("cannot write audit record")
    checked = w.check("email.delete", as_of=T0 + 10)
    assert (checked.decision.result, checked.decision.reason) == (Result.DENY, Reason.CHECK_ERROR)
    assert checked.error_kind == "persist_failed"
    assert w.store.recorded == []


def test_auth020_decision_record_complete(w: World) -> None:
    winner = rule(w, Effect.ALLOW)
    checked = w.check("email.delete", as_of=T0 + 10)
    assert len(w.store.recorded) == 1
    action, decision, used, agent_id = w.store.recorded[0]
    assert decision.path and decision.as_of == T0 + 10
    assert (action.id, decision.id) == (checked.action.id, checked.decision.id)
    assert [(u.instruction_id, u.role) for u in used] == [(winner.id, "winner")]
    kinds = [hop.type for hop in decision.path]
    assert kinds[0] == "Principal" and kinds[1] == "Utterance"
    assert kinds[-1] == "Agent" and "Instruction" in kinds and "Scope" in kinds


def test_auth020_denials_have_a_path_and_are_recorded(w: World) -> None:
    w.check("email.delete", as_of=T0 + 10)
    _, decision, used, _ = w.store.recorded[0]
    assert decision.path[-1].type == "Note"
    assert used == []


def test_auth020_persist_false_records_nothing(w: World) -> None:
    rule(w, Effect.ALLOW)
    w.check("email.delete", as_of=T0 + 10, persist=False)
    assert w.store.recorded == []


def test_auth020_action_status_follows_result(w: World) -> None:
    rule(w, Effect.CONFIRM, "email.send")
    rule(w, Effect.ALLOW, "email.read")
    assert w.check("email.read", as_of=T0 + 5, persist=False).action.status is ActionStatus.PROPOSED
    assert w.check("email.send", as_of=T0 + 5, persist=False).action.status is ActionStatus.PENDING
    assert w.check("file.read", as_of=T0 + 5, persist=False).action.status is ActionStatus.DENIED


def test_auth021_repeat_identical(w: World) -> None:
    rule(w, Effect.ALLOW)
    first = decide(w)
    second = decide(w)
    assert (first.result, first.reason, first.path, first.ignored) == (
        second.result,
        second.reason,
        second.path,
        second.ignored,
    )


def test_auth025_decisions_depend_only_on_own_store() -> None:
    first, second = World(), World()
    rule(first, Effect.ALLOW)
    assert decide(first).result is Result.ALLOW
    assert decide(second).result is Result.DENY
    # Same-shaped but distinct agent ids: one world's agent is unknown to the other.
    request_in_second = first.check("email.delete", as_of=T0 + 10, persist=False)
    assert request_in_second.decision.result is Result.ALLOW
    foreign = second.store.instructions_for_agent(first.main.id, T0 + 10)
    assert foreign == []


@pytest.mark.parametrize("effect", list(Effect))
def test_every_effect_produces_a_valid_decision(w: World, effect: Effect) -> None:
    rule(w, effect)
    assert decide(w).path
