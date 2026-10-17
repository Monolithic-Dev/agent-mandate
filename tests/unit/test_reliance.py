"""Reliance ranking over the in-memory store."""

from fakes.world import World

from mandate.authority.service import AuthorityService
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.lineage.reliance import rank_reliance
from mandate.models.domain import Channel, Effect


def decide(w: World, action: str, n: int, agent=None) -> None:  # type: ignore[no-untyped-def]
    w.check(action, f"inbox/m-{n}", agent=agent, as_of=T0 + 10_000 + n)


def test_rules_are_ranked_by_how_many_decisions_used_them(w: World) -> None:
    said = w.store.say(w.owner, "read", at=T0)
    read = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    said = w.store.say(w.owner, "confirm delete", at=T0 + 1)
    delete = w.store.rule(said, Effect.CONFIRM, "email.delete", agents=[w.main], at=T0 + 1)
    for n in range(4):
        decide(w, "email.read", n)
    decide(w, "email.delete", 9)

    rows = rank_reliance(w.store)
    assert [r.instruction_id for r in rows] == [read.id, delete.id]
    assert (rows[0].decisions, rows[0].as_winner, rows[0].agents) == (4, 4, 1)
    assert rows[0].effect == "allow" and rows[0].action_type == "email.read"
    assert rows[0].flags == () and not rows[0].needs_review


def test_a_high_impact_grant_is_flagged_but_not_marked_for_review(w: World) -> None:
    said = w.store.say(w.owner, "refunds", at=T0)
    w.store.rule(said, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, max_amount=500)
    w.check("refund.issue", "order/80", {"amount": 50}, as_of=T0 + 5_000)
    (row,) = rank_reliance(w.store)
    assert row.flags == ("grants_high_impact",) and not row.needs_review


def test_a_mixed_origin_rule_that_decided_things_needs_review(w: World) -> None:
    owner_utt = w.store.say(w.owner, "owner", at=T0)
    email = w.store.say(w.outsider, "email", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = w.store.summarise(owner_utt.id, email.id, at=T0)
    rule = w.store.rule(blended, Effect.ALLOW, "email.delete", agents=[w.main], at=T0)
    decide(w, "email.delete", 1)  # mixed can only ask for confirmation
    (row,) = rank_reliance(w.store)
    assert row.instruction_id == rule.id
    assert "mixed_origin" in row.flags and row.needs_review


def test_a_quarantined_rule_that_was_used_is_flagged(w: World) -> None:
    said = w.store.say(w.owner, "read", at=T0)
    rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    decide(w, "email.read", 1)
    w.store.quarantine(rule)
    (row,) = rank_reliance(w.store)
    assert "quarantined" in row.flags and row.needs_review


def test_a_system_with_no_decisions_has_no_reliance(w: World) -> None:
    assert rank_reliance(w.store) == []


def test_the_limit_is_respected(w: World) -> None:
    for i, action in enumerate(("email.read", "email.archive", "file.read")):
        said = w.store.say(w.owner, f"rule {i}", at=T0 + i)
        w.store.rule(said, Effect.ALLOW, action, agents=[w.main], at=T0 + i)
        w.check(action, "inbox/m-1" if action.startswith("email") else "files/a", as_of=T0 + 9_000)
    assert len(rank_reliance(w.store, limit=2)) == 2


def test_a_rule_that_took_effect_without_confirmation_is_marked(w: World) -> None:
    service = AuthorityService(w.store, w.clock)
    said = service.ingest_utterance(
        principal_id=w.owner.id, text="You may read my email.", channel=Channel.OWNER_DIRECT
    )
    w.clock.advance(1_000)
    w.check("email.read", "inbox/m-1")
    (row,) = rank_reliance(w.store)
    assert row.instruction_id == said.instructions[0].instruction.id
    assert row.flags == ("auto_activated",) and not row.needs_review
