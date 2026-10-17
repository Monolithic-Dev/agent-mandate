"""Conformance tests for AUTH-007 to AUTH-010, AUTH-012 and AUTH-026 (example form)."""

from typing import Any

from fakes.world import World

from mandate.clock import SCENARIO_T0_MS as T0
from mandate.models.domain import Decision, Effect, Instruction, Reason, Result


def allow(
    w: World,
    action: str = "email.read",
    *,
    at: int = T0,
    resource_pattern: str = "*",
    max_amount: int | None = None,
    valid_from: int | None = None,
    valid_to: int | None = None,
) -> Instruction:
    said = w.store.say(w.owner, "rule", at=at)
    return w.store.rule(
        said,
        Effect.ALLOW,
        action,
        agents=[w.main],
        at=at,
        resource_pattern=resource_pattern,
        max_amount=max_amount,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def result(
    w: World,
    as_of: int,
    action: str = "email.read",
    resource: str = "inbox/m-1",
    args: dict[str, Any] | None = None,
) -> Decision:
    return w.check(action, resource, args, as_of=as_of, persist=False).decision


def test_auth007_validity_window_edges(w: World) -> None:
    allow(w, at=T0, valid_from=T0 + 10, valid_to=T0 + 20)
    assert result(w, T0 + 9).result is Result.DENY
    assert result(w, T0 + 10).result is Result.ALLOW
    assert result(w, T0 + 19).result is Result.ALLOW
    assert result(w, T0 + 20).result is Result.DENY


def test_auth007_not_active_before_activation(w: World) -> None:
    allow(w, at=T0 + 100)
    assert result(w, T0 + 99).result is Result.DENY
    assert result(w, T0 + 100).result is Result.ALLOW


def test_auth008_revocation_as_of_uses_timestamps(w: World) -> None:
    rule = allow(w, at=T0)
    w.store.revoke(rule, at=T0 + 100)
    assert result(w, T0 + 99).result is Result.ALLOW
    revoked = result(w, T0 + 100)
    assert (revoked.result, revoked.reason) == (Result.DENY, Reason.AUTHORITY_REVOKED)
    assert result(w, T0 + 5_000).reason is Reason.AUTHORITY_REVOKED


def test_auth008_revoked_instruction_appears_in_the_path(w: World) -> None:
    rule = allow(w, at=T0)
    w.store.revoke(rule, at=T0 + 100)
    decision = result(w, T0 + 200)
    assert any(hop.type == "Instruction" and hop.id == rule.id for hop in decision.path)


def test_auth009_supersession_narrows(w: World) -> None:
    old = allow(w, at=T0)
    new = allow(w, at=T0 + 10, resource_pattern="inbox/m-9")
    w.store.supersede(new, old, at=T0 + 10)
    assert result(w, T0 + 9).result is Result.ALLOW  # before supersession
    assert result(w, T0 + 20, resource="inbox/m-1").result is Result.DENY
    assert result(w, T0 + 20, resource="inbox/m-9").result is Result.ALLOW


def test_auth009_quarantined_superseder_does_not_supersede(w: World) -> None:
    old = allow(w, at=T0)
    new = allow(w, at=T0 + 10, resource_pattern="inbox/m-9")
    w.store.supersede(new, old, at=T0 + 10)
    w.store.quarantine(new)
    assert result(w, T0 + 20, resource="inbox/m-1").result is Result.ALLOW  # old applies again


def test_auth010_quarantine_excludes(w: World) -> None:
    rule = allow(w, at=T0)
    assert result(w, T0 + 10).result is Result.ALLOW
    w.store.quarantine(rule)
    assert result(w, T0 + 10).result is Result.DENY
    w.store.quarantine(rule, False)
    assert result(w, T0 + 10).result is Result.ALLOW


def test_auth012_max_amount_inclusive(w: World) -> None:
    allow(w, "refund.issue", at=T0, max_amount=500)
    ok = result(w, T0 + 1, "refund.issue", resource="order/1", args={"amount": 500})
    over = result(w, T0 + 1, "refund.issue", resource="order/1", args={"amount": 501})
    assert ok.result is Result.ALLOW
    assert (over.result, over.reason) == (Result.DENY, Reason.CONSTRAINT_NOT_MET)


def test_auth012_missing_amount_not_applicable(w: World) -> None:
    allow(w, "refund.issue", at=T0, max_amount=500)
    decision = result(w, T0 + 1, "refund.issue", resource="order/1")
    assert decision.reason is Reason.CONSTRAINT_NOT_MET


def test_auth012_constraint_failed_path_names_the_rule(w: World) -> None:
    rule = allow(w, "refund.issue", at=T0, max_amount=500)
    decision = result(w, T0 + 1, "refund.issue", resource="order/1", args={"amount": 900})
    notes = [hop for hop in decision.path if hop.type == "Instruction"]
    assert [hop.id for hop in notes] == [rule.id]
    assert "max_amount=500" in notes[0].note


def test_auth026_future_events_ignored(w: World) -> None:
    rule = allow(w, at=T0)
    before = result(w, T0 + 50)
    # Events after the evaluation time: a revocation, a later deny, a new delegation.
    w.store.revoke(rule, at=T0 + 100)
    later = w.store.say(w.owner, "stop", at=T0 + 120)
    w.store.rule(later, Effect.DENY, "email.read", agents=[w.main], at=T0 + 120)
    w.store.delegate(w.main, w.sub, "*", at=T0 + 130)
    after = result(w, T0 + 50)
    assert (before.result, before.reason, before.path) == (after.result, after.reason, after.path)
    assert result(w, T0 + 150).result is Result.DENY
