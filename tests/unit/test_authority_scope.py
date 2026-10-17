import pytest
from hypothesis import given
from hypothesis import strategies as st

from mandate.authority.scope import (
    Applicability,
    EffectiveScope,
    applicability,
    intersect,
    intersect_action_types,
)


def scope(
    action_type: str = "email.read",
    patterns: tuple[str, ...] = ("*",),
    max_amount: int | None = None,
) -> EffectiveScope:
    return EffectiveScope("scp_x", action_type, patterns, max_amount)


# --- AUTH-011 ---


@pytest.mark.parametrize(
    ("scope_args", "action", "resource", "expected"),
    [
        (("email.read", ("inbox/*",)), "email.read", "inbox/m-1", Applicability.MATCH),
        (("email.read", ("inbox/*",)), "email.read", "files/a", Applicability.NO_MATCH),
        (("email.read", ("*",)), "email.delete", "inbox/m-1", Applicability.NO_MATCH),
        (("email.*", ("*",)), "email.delete", "inbox/m-1", Applicability.MATCH),
        (("*", ("*",)), "file.write", "files/a", Applicability.MATCH),
        (("email.read", ("inbox/*",)), "email.read", "inbox/../x", Applicability.NO_MATCH),
        (("email.read", ("*",)), "email.read", "", Applicability.NO_MATCH),
    ],
)
def test_auth011_scope_matching_table(
    scope_args: tuple[str, tuple[str, ...]], action: str, resource: str, expected: Applicability
) -> None:
    assert applicability(scope(*scope_args), action, resource, {}) is expected


def test_auth011_traversal_rejected() -> None:
    assert applicability(scope(patterns=("*",)), "email.read", "inbox/../../etc", {}) == (
        Applicability.NO_MATCH
    )


# --- AUTH-012 ---


def refund(max_amount: int | None) -> EffectiveScope:
    return scope("refund.issue", max_amount=max_amount)


def test_auth012_max_amount_inclusive() -> None:
    limited = refund(500)
    assert applicability(limited, "refund.issue", "order/1", {"amount": 500}) is Applicability.MATCH
    assert applicability(limited, "refund.issue", "order/1", {"amount": 499.99}) is (
        Applicability.MATCH
    )
    assert applicability(limited, "refund.issue", "order/1", {"amount": 501}) is (
        Applicability.CONSTRAINT_FAILED
    )


@pytest.mark.parametrize("amount", [None, "100", True, float("nan"), float("inf"), -5, [1], {}])
def test_auth012_missing_or_bad_amount_not_applicable(amount: object) -> None:
    args = {} if amount is None else {"amount": amount}
    assert applicability(refund(500), "refund.issue", "order/1", args) is (
        Applicability.CONSTRAINT_FAILED
    )


def test_auth012_no_constraint_ignores_amount() -> None:
    assert applicability(refund(None), "refund.issue", "order/1", {}) is Applicability.MATCH


def test_constraint_only_checked_when_scope_matches() -> None:
    assert applicability(refund(500), "email.read", "inbox/m", {"amount": 9999}) is (
        Applicability.NO_MATCH
    )


# --- AUTH-013 ---


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("*", "email.read", "email.read"),
        ("email.read", "*", "email.read"),
        ("email.*", "email.read", "email.read"),
        ("email.*", "email.*", "email.*"),
        ("email.*", "file.*", None),
        ("email.read", "email.delete", None),
        ("*", "*", "*"),
    ],
)
def test_auth013_action_type_intersection(a: str, b: str, expected: str | None) -> None:
    assert intersect_action_types(a, b) == expected


def test_auth013_intersection_cases() -> None:
    narrowed = intersect(
        scope("email.*", ("inbox/*",), 1000), scope("email.read", ("inbox/m-?",), 500)
    )
    assert narrowed is not None
    assert narrowed.action_type == "email.read"
    assert narrowed.resource_patterns == ("inbox/*", "inbox/m-?")
    assert narrowed.max_amount == 500


def test_auth013_empty_intersection_is_none() -> None:
    assert intersect(scope("email.read"), scope("file.read")) is None


def test_auth013_keeps_first_scope_id() -> None:
    first = EffectiveScope("scp_first", "*", ("*",))
    second = EffectiveScope("dlg_second", "email.read", ("*",))
    result = intersect(first, second)
    assert result is not None
    assert result.scope_id == "scp_first"


# --- property: narrowing never widens ---

ACTIONS = ["email.read", "email.delete", "file.read", "refund.issue"]
SCOPE_TYPES = ["*", "email.*", "file.*", "email.read", "email.delete", "refund.issue", "file.read"]
PATTERNS = ["*", "inbox/*", "files/*", "inbox/m-?"]
RESOURCES = ["inbox/m-1", "inbox/m-22", "files/a", "order/1"]

scopes = st.builds(
    EffectiveScope,
    scope_id=st.just("scp_x"),
    action_type=st.sampled_from(SCOPE_TYPES),
    resource_patterns=st.lists(st.sampled_from(PATTERNS), min_size=1, max_size=2).map(tuple),
    max_amount=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
)


@given(
    a=scopes,
    b=scopes,
    action=st.sampled_from(ACTIONS),
    resource=st.sampled_from(RESOURCES),
    amount=st.one_of(st.none(), st.integers(min_value=0, max_value=1500)),
)
def test_intersection_matches_iff_both_match(
    a: EffectiveScope, b: EffectiveScope, action: str, resource: str, amount: int | None
) -> None:
    args = {} if amount is None else {"amount": amount}
    both = (
        applicability(a, action, resource, args) is Applicability.MATCH
        and applicability(b, action, resource, args) is Applicability.MATCH
    )
    narrowed = intersect(a, b)
    narrowed_match = (
        narrowed is not None
        and applicability(narrowed, action, resource, args) is Applicability.MATCH
    )
    assert narrowed_match == both
