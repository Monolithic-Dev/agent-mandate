"""The fixed registry of action types (docs/data-model.md section 5)."""

from __future__ import annotations

ACTION_TYPES: tuple[str, ...] = (
    "email.read",
    "email.archive",
    "email.delete",
    "email.send",
    "refund.issue",
    "file.read",
    "file.write",
    "file.delete",
)

# Actions the planner treats as sinks and the UI marks as consequential.
HIGH_IMPACT: frozenset[str] = frozenset(
    {"email.delete", "email.send", "refund.issue", "file.delete"}
)


def is_registry_action(value: str) -> bool:
    """True if ``value`` is exactly one of the registered action types."""
    return value in ACTION_TYPES


def is_valid_scope_action_type(value: str) -> bool:
    """True for a registered action, ``*``, or a prefix wildcard such as ``email.*``."""
    if value == "*" or value in ACTION_TYPES:
        return True
    if value.endswith(".*"):
        prefix = value[:-1]  # keeps the trailing dot
        return any(action.startswith(prefix) for action in ACTION_TYPES)
    return False


def action_type_covers(scope_type: str, action_type: str) -> bool:
    """True if a scope's action type covers a concrete action type (AUTH-011)."""
    if scope_type == "*" or scope_type == action_type:
        return True
    return scope_type.endswith(".*") and action_type.startswith(scope_type[:-1])
