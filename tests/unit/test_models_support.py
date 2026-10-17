import pytest

from mandate.errors import ValidationFailure
from mandate.models.domain import Channel, Role, Trust
from mandate.models.registry import (
    ACTION_TYPES,
    HIGH_IMPACT,
    action_type_covers,
    is_registry_action,
    is_valid_scope_action_type,
)
from mandate.models.resources import (
    normalise_resource,
    resource_matches,
    validate_resource_pattern,
)
from mandate.models.trust import compute_trust
from mandate.models.validation import MAX_FUTURE_SKEW_MS, ensure_not_future

# --- registry ---


def test_registry_contents() -> None:
    assert len(ACTION_TYPES) == 8
    assert HIGH_IMPACT <= set(ACTION_TYPES)


@pytest.mark.parametrize("value", ["*", "email.*", "file.*", "refund.*", "email.read"])
def test_valid_scope_action_types(value: str) -> None:
    assert is_valid_scope_action_type(value)


@pytest.mark.parametrize("value", ["", "email", "email.", "mail.*", "email.fly", "**", "*.read"])
def test_invalid_scope_action_types(value: str) -> None:
    assert not is_valid_scope_action_type(value)


def test_is_registry_action_is_exact() -> None:
    assert is_registry_action("email.read")
    assert not is_registry_action("email.*")
    assert not is_registry_action("*")


@pytest.mark.parametrize(
    ("scope", "action", "expected"),
    [
        ("*", "email.read", True),
        ("email.read", "email.read", True),
        ("email.*", "email.delete", True),
        ("email.*", "file.delete", False),
        ("email.read", "email.delete", False),
        ("file.*", "file.write", True),
    ],
)
def test_action_type_covers(scope: str, action: str, expected: bool) -> None:
    assert action_type_covers(scope, action) is expected


# --- resources ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("inbox/m-1", "inbox/m-1"),
        ("  inbox/m-1  ", "inbox/m-1"),
        ("inbox//m-1/", "inbox/m-1"),
        ("./inbox/m-1", "inbox/m-1"),
        ("/inbox/m-1", "inbox/m-1"),
    ],
)
def test_normalise_resource(raw: str, expected: str) -> None:
    assert normalise_resource(raw) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "inbox/../x", "..", "a\\b", "a\x00b", "x" * 600],
)
def test_normalise_resource_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        normalise_resource(bad)


def test_validate_resource_pattern() -> None:
    assert validate_resource_pattern(" inbox/* ") == "inbox/*"
    for bad in ["", "../x", "a\\b"]:
        with pytest.raises(ValueError):
            validate_resource_pattern(bad)


@pytest.mark.parametrize(
    ("pattern", "resource", "expected"),
    [
        ("inbox/*", "inbox/m-1", True),
        ("inbox/*", "files/a", False),
        ("*", "anything/at/all", True),
        ("inbox/m-?", "inbox/m-1", True),
        ("Inbox/*", "inbox/m-1", False),
        ("inbox/*", "inbox/../secret", False),
        ("*", "", False),
    ],
)
def test_resource_matches(pattern: str, resource: str, expected: bool) -> None:
    assert resource_matches(pattern, resource) is expected


# --- trust (AUTH-002) ---


@pytest.mark.parametrize(
    ("channel", "role", "expected"),
    [
        (Channel.OWNER_DIRECT, Role.OWNER, Trust.TRUSTED),
        (Channel.OWNER_DIRECT, Role.EXTERNAL, Trust.UNTRUSTED),
        (Channel.UNTRUSTED_CONTENT, Role.OWNER, Trust.UNTRUSTED),
        (Channel.UNTRUSTED_CONTENT, Role.EXTERNAL, Trust.UNTRUSTED),
    ],
)
def test_compute_trust(channel: Channel, role: Role, expected: Trust) -> None:
    assert compute_trust(channel, role) is expected


# --- time validation ---


def test_ensure_not_future() -> None:
    now = 1_000_000
    assert ensure_not_future(now, now) == now
    assert ensure_not_future(now + MAX_FUTURE_SKEW_MS, now)
    with pytest.raises(ValidationFailure):
        ensure_not_future(now + MAX_FUTURE_SKEW_MS + 1, now)
    with pytest.raises(ValidationFailure):
        ensure_not_future(-1, now)
