"""Identifier generation and validation.

An id is ``<prefix>_<26 characters>``: 10 characters of millisecond time followed by
16 characters of randomness, both in Crockford base32 (uppercase). Ids therefore sort by
creation time. See docs/data-model.md section 1.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable

PREFIXES = frozenset(
    {
        "prn",
        "utt",
        "ins",
        "scp",
        "agt",
        "sum",
        "act",
        "dec",
        "apr",
        "dlg",
        "tok",
        "usr",
        "aud",
        "ses",
        "whk",
        "dlv",
    }
)
ID_RE = re.compile(
    r"^(prn|utt|ins|scp|agt|sum|act|dec|apr|dlg|tok|usr|aud|ses|whk|dlv)_[0-9A-Z]{26}$"
)

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_CHARS = 10
_RANDOM_CHARS = 16
RANDOM_BITS = _RANDOM_CHARS * 5


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(
    prefix: str,
    *,
    now_ms: int | None = None,
    randbits: Callable[[int], int] = secrets.randbits,
) -> str:
    """Create a new id for ``prefix``.

    ``now_ms`` and ``randbits`` can be supplied for deterministic tests.
    """
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix!r}")
    timestamp = now_ms if now_ms is not None else time.time_ns() // 1_000_000
    if timestamp < 0 or timestamp >= 1 << (_TIME_CHARS * 5):
        raise ValueError("timestamp out of range")
    time_part = _encode(timestamp, _TIME_CHARS)
    random_part = _encode(randbits(RANDOM_BITS), _RANDOM_CHARS)
    return f"{prefix}_{time_part}{random_part}"


def is_valid_id(value: str, prefix: str | None = None) -> bool:
    """Return True if ``value`` is a well-formed id, optionally of a given prefix."""
    if not ID_RE.match(value):
        return False
    return prefix is None or value.startswith(f"{prefix}_")


class MonotonicIds:
    """Ids that sort in the order they were made, even within one millisecond: the random
    part of an id in the same millisecond as the last is the last one's plus one. For logs
    read newest first (audit events, webhook deliveries)."""

    def __init__(self, prefix: str) -> None:
        if prefix not in PREFIXES:
            raise ValueError(f"unknown id prefix: {prefix!r}")
        self._prefix = prefix
        self._lock = threading.Lock()
        self._last_ms = -1
        self._last_random = 0

    def next(self, now_ms: int) -> str:
        with self._lock:
            if now_ms <= self._last_ms:
                now_ms, value = self._last_ms, self._last_random + 1
            else:
                value = secrets.randbits(RANDOM_BITS - 1)  # headroom for increments
            self._last_ms, self._last_random = now_ms, value
        return new_id(self._prefix, now_ms=now_ms, randbits=lambda _bits: value)
