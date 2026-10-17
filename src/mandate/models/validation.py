"""Checks that need the current time and so cannot live in the models themselves."""

from __future__ import annotations

from mandate.errors import ValidationFailure

MAX_FUTURE_SKEW_MS = 5 * 60 * 1000


def ensure_not_future(timestamp_ms: int, now_ms: int, *, skew_ms: int = MAX_FUTURE_SKEW_MS) -> int:
    """Reject negative timestamps and ones more than ``skew_ms`` ahead of ``now_ms``."""
    if timestamp_ms < 0:
        raise ValidationFailure("timestamp must be non-negative")
    if timestamp_ms > now_ms + skew_ms:
        raise ValidationFailure("timestamp is too far in the future")
    return timestamp_ms
