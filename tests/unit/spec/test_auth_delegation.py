"""Conformance tests for AUTH-013 to AUTH-016."""

from typing import Any

from fakes.world import World

from mandate.authority.delegation import MAX_CHAIN_DEPTH
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.models.domain import Agent, AgentKind, Decision, Effect, Reason, Result


def main_rule(w: World, effect: Effect, action: str, *, at: int = T0, **kw: Any) -> None:
    said = w.store.say(w.owner, "rule", at=at)
    w.store.rule(said, effect, action, agents=[w.main], at=at, **kw)


def sub_check(
    w: World,
    as_of: int,
    action: str = "email.read",
    resource: str = "inbox/m-1",
    args: dict[str, Any] | None = None,
) -> Decision:
    return w.check(action, resource, args, agent=w.sub, as_of=as_of, persist=False).decision


def test_auth013_intersection_cases(w: World) -> None:
    main_rule(w, Effect.ALLOW, "email.*")
    w.store.delegate(w.main, w.sub, "email.read", resource_pattern="inbox/*", at=T0)
    assert sub_check(w, T0 + 1).result is Result.ALLOW
    outside_action = sub_check(w, T0 + 1, "email.delete")
    assert (outside_action.result, outside_action.reason) == (
        Result.DENY,
        Reason.NO_AUTHORITY_PATH,
    )
    assert sub_check(w, T0 + 1, "email.read", "files/a").result is Result.DENY


def test_auth013_amount_limit_is_the_minimum(w: World) -> None:
    main_rule(w, Effect.ALLOW, "refund.issue", max_amount=1000)
    w.store.delegate(w.main, w.sub, "refund.issue", max_amount=200, at=T0)
    ok = sub_check(w, T0 + 1, "refund.issue", "order/1", {"amount": 200})
    over = sub_check(w, T0 + 1, "refund.issue", "order/1", {"amount": 201})
    assert ok.result is Result.ALLOW
    assert over.reason is Reason.CONSTRAINT_NOT_MET


def test_auth013_delegate_cannot_exceed_delegator(w: World) -> None:
    main_rule(w, Effect.ALLOW, "email.read")
    w.store.delegate(w.main, w.sub, "*", at=T0)  # delegation is broader than the delegator
    assert sub_check(w, T0 + 1, "email.read").result is Result.ALLOW
    assert sub_check(w, T0 + 1, "email.delete").result is Result.DENY


def test_auth014_delegation_time_and_revocation(w: World) -> None:
    main_rule(w, Effect.ALLOW, "email.read")
    delegation = w.store.delegate(w.main, w.sub, "email.read", at=T0 + 10)
    assert sub_check(w, T0 + 9).result is Result.DENY  # not yet created
    assert sub_check(w, T0 + 10).result is Result.ALLOW
    w.store.revoke_delegation(delegation, at=T0 + 50)
    assert sub_check(w, T0 + 49).result is Result.ALLOW
    revoked = sub_check(w, T0 + 50)
    assert (revoked.result, revoked.reason) == (Result.DENY, Reason.AUTHORITY_REVOKED)


def test_auth014_expired_delegation_is_inactive_not_revoked(w: World) -> None:
    main_rule(w, Effect.ALLOW, "email.read")
    w.store.delegate(w.main, w.sub, "email.read", at=T0, valid_to=T0 + 30)
    assert sub_check(w, T0 + 29).result is Result.ALLOW
    expired = sub_check(w, T0 + 30)
    assert (expired.result, expired.reason) == (Result.DENY, Reason.NO_AUTHORITY_PATH)


def test_delegator_rule_revoked_blocks_delegate(w: World) -> None:
    said = w.store.say(w.owner, "rule", at=T0)
    rule = w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.main], at=T0)
    w.store.delegate(w.main, w.sub, "email.read", at=T0)
    assert sub_check(w, T0 + 10).result is Result.ALLOW
    w.store.revoke(rule, at=T0 + 20)
    assert sub_check(w, T0 + 20).result is Result.DENY


def test_auth015_deny_flows_down(w: World) -> None:
    main_rule(w, Effect.ALLOW, "email.*", at=T0)
    main_rule(w, Effect.DENY, "email.delete", at=T0 + 10)
    w.store.delegate(w.main, w.sub, "email.*", at=T0)
    denied = sub_check(w, T0 + 20, "email.delete")
    assert (denied.result, denied.reason) == (Result.DENY, Reason.EXPLICIT_DENY)
    assert sub_check(w, T0 + 20, "email.read").result is Result.ALLOW


def _agents(w: World, count: int) -> list[Agent]:
    return [w.store.add_agent(f"a{i}", AgentKind.SUB) for i in range(count)]


def test_auth016_depth_limit(w: World) -> None:
    agents = _agents(w, MAX_CHAIN_DEPTH + 2)  # a0 .. a5: five hops from a0 to a5
    for upstream, downstream in zip(agents, agents[1:], strict=False):
        w.store.delegate(upstream, downstream, "email.read", at=T0)
    said = w.store.say(w.owner, "rule", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[agents[0]], at=T0)
    last = agents[-1]
    assert w.check("email.read", agent=last, as_of=T0 + 1, persist=False).decision.result is (
        Result.DENY
    )
    # A rule held one hop closer (four hops from the last agent) does flow.
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[agents[1]], at=T0)
    assert w.check("email.read", agent=last, as_of=T0 + 1, persist=False).decision.result is (
        Result.ALLOW
    )


def test_auth016_cycle_terminates(w: World) -> None:
    w.store.delegate(w.main, w.sub, "email.read", at=T0)
    w.store.delegate(w.sub, w.main, "email.read", at=T0)
    said = w.store.say(w.owner, "rule", at=T0)
    w.store.rule(said, Effect.ALLOW, "email.read", agents=[w.sub], at=T0)
    decision = w.check("email.read", agent=w.main, as_of=T0 + 1, persist=False).decision
    assert decision.result is Result.ALLOW  # authority flows sub -> main once, no loop


def test_delegation_path_lists_the_delegation(w: World) -> None:
    main_rule(w, Effect.ALLOW, "email.read")
    delegation = w.store.delegate(w.main, w.sub, "email.read", at=T0)
    decision = sub_check(w, T0 + 1)
    kinds = [(hop.type, hop.id) for hop in decision.path]
    assert ("Delegation", delegation.id) in kinds
    assert kinds[-1] == ("Agent", w.sub.id)
