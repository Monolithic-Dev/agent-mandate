"""Metrics with honest uncertainty: every rate carries its n and a Wilson interval."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    successes: int
    total: int

    @property
    def value(self) -> float | None:
        return self.successes / self.total if self.total else None

    def interval(self, z: float = 1.96) -> tuple[float, float] | None:
        return wilson_interval(self.successes, self.total, z)

    def format(self) -> str:
        if not self.total:
            return "n/a (n=0)"
        low, high = self.interval() or (0.0, 0.0)
        return f"{self.successes}/{self.total} = {self.value:.1%} (95% CI {low:.1%} to {high:.1%})"


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion. Returns None when there is no data."""
    if total <= 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("successes must be between 0 and total")
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def count(flags: Iterable[bool]) -> int:
    return sum(1 for flag in flags if flag)
