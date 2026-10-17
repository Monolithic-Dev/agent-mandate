"""Time source.

All time in the system is epoch milliseconds (integer). Code that needs the current time
takes a ``Clock`` so tests and evaluation scenarios can control it.
"""

from __future__ import annotations

import time
from typing import Protocol

# Default start for scenarios: T0 in docs/scenarios.md.
SCENARIO_T0_MS = 1_760_500_000_000


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    """Wall-clock time."""

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class FixedClock:
    """A controllable clock for tests and scripted scenarios."""

    def __init__(self, start_ms: int = SCENARIO_T0_MS) -> None:
        if start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def advance(self, ms: int) -> int:
        """Move time forward by ``ms`` milliseconds and return the new time."""
        if ms < 0:
            raise ValueError("cannot move a FixedClock backwards")
        self._now += ms
        return self._now

    def set(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("ms must be non-negative")
        self._now = ms
