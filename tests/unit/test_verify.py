"""The explanation verifier: honest paths verify, and every kind of lie is caught."""

from typing import Any

import pytest
from fakes.world import World

from mandate.authority.ports import UsedInstruction
from mandate.authority.verify import verify_decision
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.models.domain import Channel, Effect, PathHop


def decided(w: World, action: str, resource: str = "inbox/m-1", **kw: Any) -> str:
    return w.check(action, resource, as_of=T0 + 10_000, **kw).decision.id


def names(v: Any) -> set[str]:
    return {check.name for check in v.failures}


# --- honest decisions verify ----------------------------------------------------------


def test_an_allow_decision_verifies(w: World) -> None:
    said = w.store.say(w.owner, "read", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    result = verify_decision(w.store, decided(w, "email.read"))
    assert result.ok, result.failures
    assert len(result.checks) >= 8


def test_a_deny_and_a_confirm_verify(w: World) -> None:
    said = w.store.say(w.owner, "rules", at=T0)
    w.store.rule(said, Effect.DENY, "email.delete", agents=[w.main], at=T0)
    w.store.rule(said, Effect.CONFIRM, "email.send", agents=[w.main], at=T0)
    assert verify_decision(w.store, decided(w, "email.delete")).ok
    assert verify_decision(w.store, decided(w, "email.send")).ok


def test_a_refund_within_its_limit_verifies(w: World) -> None:
    said = w.store.say(w.owner, "refunds", at=T0)
    w.store.rule(said, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, max_amount=500)
    result = verify_decision(w.store, decided(w, "refund.issue", "order/1", args={"amount": 200}))
    assert result.ok
    assert "the amount is within the limit" in {c.name for c in result.checks}


def test_a_delegated_allow_verifies(w: World) -> None:
    said = w.store.say(w.owner, "read", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    w.store.delegate(w.main, w.sub, "email.read", at=T0)
    result = verify_decision(w.store, decided(w, "email.read", agent=w.sub))
    assert result.ok, result.failures
    assert "the delegations form one real chain to the acting agent" in {
        c.name for c in result.checks
    }


def test_a_mixed_origin_confirmation_verifies(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(owner_utt.id, email.id, at=T0)
    w.store.rule(blended, Effect.ALLOW, "email.delete", agents=[w.main], at=T0)
    assert verify_decision(w.store, decided(w, "email.delete")).ok


def test_an_old_decision_still_verifies_after_the_rule_is_revoked(w: World) -> None:
    said = w.store.say(w.owner, "read", at=T0)
    rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    before = decided(w, "email.read")
    w.store.revoke(rule, at=T0 + 20_000)  # after the decision's own moment
    assert verify_decision(w.store, before).ok  # judged as of its time, not now


def test_a_denial_without_a_rule_verifies(w: World) -> None:
    result = verify_decision(w.store, decided(w, "email.read"))
    assert result.ok and {c.name for c in result.checks} >= {"acting agent exists"}


# --- every lie is caught --------------------------------------------------------------


def tamper(w: World, decision_id: str, **changes: Any) -> None:
    """Rewrite a stored decision the way a bug or an attacker with database access might."""
    for index, (action, decision, used, agent) in enumerate(w.store.recorded):
        if decision.id == decision_id:
            decision = decision.model_copy(update=changes.pop("decision", {}))
            action = action.model_copy(update=changes.pop("action", {}))
            used = changes.pop("used", used)
            agent = changes.pop("agent", agent)
            w.store.recorded[index] = (action, decision, used, agent)
            return
    raise AssertionError("no such decision")


@pytest.fixture
def allowed(w: World) -> tuple[World, str, str]:
    said = w.store.say(w.owner, "read", at=T0)
    rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    return w, decided(w, "email.read"), rule.id


def replace_hop(path: list[PathHop], kind: str, new_id: str) -> list[PathHop]:
    return [PathHop(type=h.type, id=new_id) if h.type == kind else h for h in path]


def test_a_path_that_names_another_agent_is_caught(allowed: tuple[World, str, str]) -> None:
    w, decision_id, _ = allowed
    path = w.store.get_decision(decision_id).decision.path
    tamper(w, decision_id, decision={"path": replace_hop(list(path), "Agent", w.sub.id)})
    assert "path names the acting agent" in names(verify_decision(w.store, decision_id))


def test_a_cited_rule_that_was_never_used_is_caught(allowed: tuple[World, str, str]) -> None:
    w, decision_id, _ = allowed
    other = w.store.rule(
        w.store.say(w.owner, "x", at=T0), Effect.ALLOW, "email.archive", agents=[w.main], at=T0
    )
    path = w.store.get_decision(decision_id).decision.path
    tamper(w, decision_id, decision={"path": replace_hop(list(path), "Instruction", other.id)})
    failed = names(verify_decision(w.store, decision_id))
    assert "every rule in the path was recorded as used" in failed
    assert "the path names the winning rule" in failed


def test_a_fabricated_rule_id_is_caught(allowed: tuple[World, str, str]) -> None:
    w, decision_id, _ = allowed
    path = w.store.get_decision(decision_id).decision.path
    ghost = "ins_" + "Z" * 26
    tamper(
        w,
        decision_id,
        decision={"path": replace_hop(list(path), "Instruction", ghost)},
        used=[UsedInstruction(ghost, "winner")],
    )
    assert "every cited rule exists" in names(verify_decision(w.store, decision_id))


def test_a_fabricated_speaker_or_utterance_is_caught(allowed: tuple[World, str, str]) -> None:
    w, decision_id, _ = allowed
    path = w.store.get_decision(decision_id).decision.path
    forged = replace_hop(
        replace_hop(list(path), "Principal", w.outsider.id), "Utterance", "utt_FAKE"
    )
    tamper(w, decision_id, decision={"path": forged})
    failed = names(verify_decision(w.store, decision_id))
    assert "the cited speaker said the cited utterance" in failed
    assert "the cited utterances and summaries are on the rule's origin chain" in failed


def test_a_result_that_contradicts_the_rule_is_caught(allowed: tuple[World, str, str]) -> None:
    w, decision_id, _ = allowed
    from mandate.models.domain import Result

    tamper(w, decision_id, decision={"result": Result.DENY})
    assert "the winner's effect fits the result" in names(verify_decision(w.store, decision_id))


def test_an_action_outside_the_rules_scope_is_caught(allowed: tuple[World, str, str]) -> None:
    w, decision_id, _ = allowed
    tamper(w, decision_id, action={"action_type": "email.delete", "resource": "files/secret"})
    failed = names(verify_decision(w.store, decision_id))
    assert "the scope covers the action type" in failed


def test_a_decision_made_before_the_rule_existed_is_caught(
    allowed: tuple[World, str, str],
) -> None:
    w, decision_id, _ = allowed
    tamper(w, decision_id, decision={"as_of": T0 - 1})
    failed = names(verify_decision(w.store, decision_id))
    assert "the winner was active when the decision was made" in failed


def test_an_amount_over_the_limit_is_caught(w: World) -> None:
    said = w.store.say(w.owner, "refunds", at=T0)
    w.store.rule(said, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, max_amount=500)
    decision_id = decided(w, "refund.issue", "order/1", args={"amount": 200})
    tamper(w, decision_id, action={"args": {"amount": 9000}})
    assert "the amount is within the limit" in names(verify_decision(w.store, decision_id))


def test_a_trusted_claim_over_an_untrusted_origin_is_caught(w: World) -> None:
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    rule = w.store.rule(email, Effect.ALLOW, "email.read", agents=[w.main], at=T0, activate=False)
    allowed_id = decided(w, "email.read")  # honestly denied: the rule is inert
    from mandate.models.domain import Reason, Result

    tamper(
        w,
        allowed_id,
        decision={"result": Result.ALLOW, "reason": Reason.AUTHORIZED},
        used=[UsedInstruction(rule.id, "winner")],
    )
    failed = names(verify_decision(w.store, allowed_id))
    assert "the rule's origin has the trust the decision needed" in failed


def test_a_delegation_chain_that_does_not_exist_is_caught(w: World) -> None:
    said = w.store.say(w.owner, "read", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    real = w.store.delegate(w.main, w.sub, "email.read", at=T0)
    decision_id = decided(w, "email.read", agent=w.sub)
    path = list(w.store.get_decision(decision_id).decision.path)
    fake = [PathHop(type=h.type, id="dlg_FAKE") if h.type == "Delegation" else h for h in path]
    assert any(h.id == real.id for h in path)
    tamper(w, decision_id, decision={"path": fake})
    failed = names(verify_decision(w.store, decision_id))
    assert "the delegations form one real chain to the acting agent" in failed


def test_a_missing_decision_is_not_found(w: World) -> None:
    from mandate.errors import NotFound

    with pytest.raises(NotFound):
        verify_decision(w.store, "dec_" + "0" * 26)
