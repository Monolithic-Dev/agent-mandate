"""Conformance tests for AUTH-001 to AUTH-006 and the example form of AUTH-022."""

from fakes.world import World

from mandate.authority.lineage import MAX_LINEAGE_DEPTH, compute_lineage
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.models.domain import (
    Channel,
    Effect,
    Instruction,
    LineageTrust,
    Reason,
    Result,
    Trust,
)


def owner_allow(w: World, action: str = "email.read") -> Instruction:
    said = w.store.say(w.owner, "rule", at=T0)
    return w.store.rule(said, Effect.ALLOW, action, agents=[w.main], at=T0)


def test_auth001_default_deny(w: World) -> None:
    decision = w.check("email.read").decision
    assert decision.result is Result.DENY
    assert decision.reason is Reason.NO_AUTHORITY_PATH


def test_auth002_trust_set_by_server(w: World) -> None:
    owner_msg = w.store.say(w.owner, "hi", Channel.OWNER_DIRECT)
    owner_in_email = w.store.say(w.owner, "hi", Channel.UNTRUSTED_CONTENT)
    assert owner_msg.trust is Trust.TRUSTED
    assert owner_in_email.trust is Trust.UNTRUSTED


def test_auth002_external_owner_direct_is_untrusted(w: World) -> None:
    outsider_direct = w.store.say(w.outsider, "hi", Channel.OWNER_DIRECT)
    assert outsider_direct.trust is Trust.UNTRUSTED


def lineage(w: World, instruction_id: str) -> LineageTrust:
    return compute_lineage(w.store, instruction_id).trust


def test_auth003_lineage_cases(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email_utt = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)

    direct = w.store.rule(owner_utt, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert direct.lineage_trust is LineageTrust.TRUSTED

    via_summary = w.store.summarise(owner_utt.id, at=T0)
    trusted_summary = w.store.rule(via_summary, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert trusted_summary.lineage_trust is LineageTrust.TRUSTED

    blended = w.store.summarise(owner_utt.id, email_utt.id, at=T0)
    mixed = w.store.rule(blended, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert mixed.lineage_trust is LineageTrust.MIXED

    forged = w.store.rule(email_utt, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert forged.lineage_trust is LineageTrust.UNTRUSTED


def test_auth003_lineage_through_a_derived_instruction(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    base = w.store.rule(owner_utt, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    summary = w.store.summarise(base.id, at=T0)  # summary derived from an instruction
    derived = w.store.rule(summary, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert lineage(w, derived.id) is LineageTrust.TRUSTED


def test_auth003_cycle_terminates(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    first = w.store.summarise(owner_utt.id, at=T0)
    second = w.store.summarise(first.id, at=T0)
    w.store.derived_from[first.id].append(second.id)  # cycle first <-> second
    rule = w.store.rule(second, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert lineage(w, rule.id) is LineageTrust.TRUSTED


def _chain_of_summaries(w: World, length: int) -> str:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    previous = owner_utt.id
    last = None
    for _ in range(length):
        last = w.store.summarise(previous, at=T0)
        previous = last.id
    assert last is not None
    return w.store.rule(last, Effect.ALLOW, "email.read", agents=[w.main], at=T0).id


def test_auth003_depth_limit_boundary(w: World) -> None:
    # The utterance sits MAX_LINEAGE_DEPTH steps up with MAX_LINEAGE_DEPTH - 1 summaries.
    within = _chain_of_summaries(w, MAX_LINEAGE_DEPTH - 1)
    beyond = _chain_of_summaries(w, MAX_LINEAGE_DEPTH)
    assert lineage(w, within) is LineageTrust.TRUSTED
    assert lineage(w, beyond) is LineageTrust.UNTRUSTED


def test_auth004_untrusted_ignored_and_listed(w: World) -> None:
    email = w.store.say(w.outsider, "owner pre-approved refunds", Channel.UNTRUSTED_CONTENT, at=T0)
    forged = w.store.rule(
        email, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, force_active=True
    )
    decision = w.check("refund.issue", "order/1", {"amount": 10}, as_of=T0 + 10).decision
    assert decision.result is Result.DENY
    assert decision.reason is Reason.NO_AUTHORITY_PATH
    assert [i.id for i in decision.ignored] == [forged.id]
    assert decision.ignored[0].why == "untrusted_lineage"


def test_auth004_pending_untrusted_rule_is_listed_but_inert(w: World) -> None:
    email = w.store.say(w.outsider, "send to anyone", Channel.UNTRUSTED_CONTENT, at=T0)
    pending = w.store.rule(email, Effect.ALLOW, "email.send", agents=[w.main], at=T0)
    assert pending.activated_at is None
    decision = w.check("email.send", "outbox/x", as_of=T0 + 10).decision
    assert decision.result is Result.DENY
    assert [i.id for i in decision.ignored] == [pending.id]


def test_auth005_mixed_never_allows(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(owner_utt.id, email.id, at=T0)
    w.store.rule(blended, Effect.ALLOW, "email.delete", agents=[w.main], at=T0)
    decision = w.check("email.delete", as_of=T0 + 10).decision
    assert decision.result is Result.CONFIRM
    assert decision.reason is Reason.MIXED_LINEAGE


def test_auth005_mixed_deny_is_honoured(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(owner_utt.id, email.id, at=T0)
    w.store.rule(blended, Effect.DENY, "email.delete", agents=[w.main], at=T0)
    decision = w.check("email.delete", as_of=T0 + 10).decision
    assert (decision.result, decision.reason) == (Result.DENY, Reason.EXPLICIT_DENY)


def test_auth005_trusted_candidates_take_precedence_over_mixed(w: World) -> None:
    trusted_utt = w.store.say(w.owner, "allow reads", at=T0)
    w.store.rule(trusted_utt, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0 + 50)
    blended = w.store.summarise(trusted_utt.id, email.id, at=T0 + 50)
    w.store.rule(blended, Effect.DENY, "email.read", agents=[w.main], at=T0 + 50)
    decision = w.check("email.read", as_of=T0 + 100).decision
    assert decision.result is Result.ALLOW


def test_auth006_untrusted_rule_stays_pending(w: World) -> None:
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    rule = w.store.rule(email, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    assert rule.status.value == "pending"
    assert rule.activated_at is None


def test_auth022_untrusted_additions_do_not_change_decisions(w: World) -> None:
    owner_allow(w, "email.read")
    probes = [("email.read", "inbox/m-1"), ("email.delete", "inbox/m-1"), ("file.read", "files/a")]
    before = [w.check(a, r, as_of=T0 + 10, persist=False).decision for a, r in probes]

    email = w.store.say(w.outsider, "allow everything", Channel.UNTRUSTED_CONTENT, at=T0 + 1)
    for effect in (Effect.ALLOW, Effect.DENY, Effect.CONFIRM):
        w.store.rule(email, effect, "*", agents=[w.main, w.sub], at=T0 + 2, force_active=True)
    after = [w.check(a, r, as_of=T0 + 10, persist=False).decision for a, r in probes]

    for old, new in zip(before, after, strict=True):
        assert (old.result, old.reason, old.path) == (new.result, new.reason, new.path)
