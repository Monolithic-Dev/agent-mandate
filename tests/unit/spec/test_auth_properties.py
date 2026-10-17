"""Property-based conformance tests: AUTH-022, AUTH-023, AUTH-024 and AUTH-026.

Worlds are generated from small alphabets so hypothesis explores interesting overlaps.
"""

from dataclasses import dataclass

from fakes.world import World
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mandate.clock import SCENARIO_T0_MS as T0
from mandate.models.domain import Channel, Decision, Effect, Instruction, Result

ACTIONS = ["email.read", "email.delete", "email.send"]
SCOPE_TYPES = ["*", "email.*", "email.read", "email.delete", "email.send"]
RESOURCES = ["inbox/m-1", "inbox/m-2"]
PATTERNS = ["*", "inbox/*", "inbox/m-1"]
RANK = {Result.DENY: 0, Result.CONFIRM: 1, Result.ALLOW: 2}

PROP = settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@dataclass(frozen=True)
class RuleSpec:
    effect: Effect
    scope_type: str
    pattern: str
    at: int  # activation offset from T0


rule_specs = st.builds(
    RuleSpec,
    effect=st.sampled_from(list(Effect)),
    scope_type=st.sampled_from(SCOPE_TYPES),
    pattern=st.sampled_from(PATTERNS),
    at=st.integers(min_value=0, max_value=50),
)
rule_lists = st.lists(rule_specs, min_size=0, max_size=6)


def build(w: World, specs: list[RuleSpec]) -> list[Instruction]:
    rules = []
    for spec in specs:
        said = w.store.say(w.owner, "rule", at=T0 + spec.at)
        rules.append(
            w.store.rule(
                said,
                spec.effect,
                spec.scope_type,
                resource_pattern=spec.pattern,
                agents=[w.main],
                at=T0 + spec.at,
            )
        )
    return rules


def probes(w: World, agent_t: int, *, sub: bool = False) -> list[Decision]:
    agent = w.sub if sub else w.main
    return [
        w.check(action, resource, agent=agent, as_of=T0 + agent_t, persist=False).decision
        for action in ACTIONS
        for resource in RESOURCES
    ]


def same(a: Decision, b: Decision) -> bool:
    return (a.result, a.reason, a.path) == (b.result, b.reason, b.path)


@PROP
@given(
    specs=rule_lists,
    noise=st.lists(
        st.tuples(st.sampled_from(list(Effect)), st.sampled_from(SCOPE_TYPES)), max_size=5
    ),
)
def test_auth022_untrusted_non_interference(
    specs: list[RuleSpec], noise: list[tuple[Effect, str]]
) -> None:
    w = World()
    build(w, specs)
    before = probes(w, 100)
    email = w.store.say(w.outsider, "attacker text", Channel.UNTRUSTED_CONTENT, at=T0 + 1)
    for effect, scope_type in noise:
        w.store.rule(
            email, effect, scope_type, agents=[w.main, w.sub], at=T0 + 2, force_active=True
        )
    after = probes(w, 100)
    assert all(same(x, y) for x, y in zip(before, after, strict=True))


@PROP
@given(specs=rule_lists, pick=st.integers(min_value=0, max_value=5))
def test_auth023_revoke_allow_never_increases_permissiveness(
    specs: list[RuleSpec], pick: int
) -> None:
    w = World()
    rules = build(w, specs)
    allows = [r for r in rules if r.effect is Effect.ALLOW]
    if not allows:
        return
    before = probes(w, 100)
    w.store.revoke(allows[pick % len(allows)], at=T0 + 60)
    after = probes(w, 100)
    assert all(RANK[a.result] <= RANK[b.result] for b, a in zip(before, after, strict=True))


@PROP
@given(
    specs=rule_lists,
    delegated=st.sampled_from(SCOPE_TYPES),
    pattern=st.sampled_from(PATTERNS),
)
def test_auth024_delegate_not_more_permissive(
    specs: list[RuleSpec], delegated: str, pattern: str
) -> None:
    w = World()
    build(w, specs)
    w.store.delegate(w.main, w.sub, delegated, resource_pattern=pattern, at=T0)
    at_main = probes(w, 100)
    at_sub = probes(w, 100, sub=True)
    for main_decision, sub_decision in zip(at_main, at_sub, strict=True):
        if sub_decision.result is Result.ALLOW:
            assert main_decision.result is Result.ALLOW


ops = st.lists(
    st.tuples(
        st.sampled_from(["rule", "revoke", "delegate"]),
        st.integers(min_value=0, max_value=100),
        st.sampled_from(list(Effect)),
        st.sampled_from(SCOPE_TYPES),
    ),
    min_size=1,
    max_size=8,
)


def apply(w: World, op: tuple[str, int, Effect, str], created: list[Instruction]) -> None:
    kind, offset, effect, scope_type = op
    at = T0 + offset
    if kind == "rule":
        said = w.store.say(w.owner, "rule", at=at)
        created.append(w.store.rule(said, effect, scope_type, agents=[w.main], at=at))
    elif kind == "revoke" and created:
        w.store.revoke(created[offset % len(created)], at=at)
    elif kind == "delegate":
        w.store.delegate(w.main, w.sub, scope_type, at=at)


@PROP
@given(operations=ops)
def test_auth026_future_events_ignored(operations: list[tuple[str, int, Effect, str]]) -> None:
    t = 50
    early = [op for op in operations if op[1] <= t]
    late = [op for op in operations if op[1] > t]

    w = World()
    created: list[Instruction] = []
    for op in early:
        apply(w, op, created)
    before = probes(w, t) + probes(w, t, sub=True)
    for op in late:
        apply(w, op, created)
    after = probes(w, t) + probes(w, t, sub=True)
    assert all(same(x, y) for x, y in zip(before, after, strict=True))
