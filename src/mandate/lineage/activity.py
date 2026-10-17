"""Activity: what the tenant's agents asked for, and how it was decided, over a window.

Pure: takes decision rows (``AuthorityStore.decision_activity``) and the window, returns the
counts the console's overview draws. Buckets cover the whole window, empty ones included, so a
quiet hour shows as quiet rather than missing.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from mandate.authority.ports import ActivityRow

RESULTS = ("allow", "confirm", "deny")
MAX_ROWS = 20_000  # a window is read whole up to this many decisions


@dataclass(frozen=True)
class Bucket:
    start: int
    allow: int = 0
    confirm: int = 0
    deny: int = 0


@dataclass(frozen=True)
class Count:
    key: str
    count: int


@dataclass(frozen=True)
class Activity:
    since: int
    until: int
    bucket_ms: int
    total: int
    truncated: bool
    results: dict[str, int]
    buckets: list[Bucket] = field(default_factory=list)
    reasons: list[Count] = field(default_factory=list)
    actions: list[Count] = field(default_factory=list)
    agents: list[Count] = field(default_factory=list)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_max_ms: float | None = None


def bucket_size(hours: int) -> int:
    """Hourly up to a day, then six-hourly: never more than 28 bars."""
    return 3_600_000 if hours <= 24 else 6 * 3_600_000


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an ascending list (not empty)."""
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def window(now: int, hours: int) -> tuple[int, int, int]:
    """(since, until, bucket size): whole buckets, the last one holding ``now``."""
    size = bucket_size(hours)
    until = (now // size + 1) * size
    return until - math.ceil(hours * 3_600_000 / size) * size, until, size


def summarise(rows: list[ActivityRow], *, now: int, hours: int, truncated: bool) -> Activity:
    since, until, size = window(now, hours)
    counts: dict[int, Counter[str]] = {start: Counter() for start in range(since, until, size)}
    for row in rows:
        if since <= row.at < until:
            counts[since + (row.at - since) // size * size][row.result] += 1
    latencies = sorted(row.latency_ms for row in rows)
    results = Counter(row.result for row in rows)
    return Activity(
        since=since,
        until=until,
        bucket_ms=size,
        total=len(rows),
        truncated=truncated,
        results={result: results.get(result, 0) for result in RESULTS},
        buckets=[Bucket(start, c["allow"], c["confirm"], c["deny"]) for start, c in counts.items()],
        reasons=[Count(k, n) for k, n in Counter(r.reason for r in rows).most_common(8)],
        actions=[Count(k, n) for k, n in Counter(r.action_type for r in rows).most_common(8)],
        agents=[Count(k, n) for k, n in Counter(r.agent_id for r in rows).most_common(8)],
        latency_p50_ms=round(percentile(latencies, 0.5), 1) if latencies else None,
        latency_p95_ms=round(percentile(latencies, 0.95), 1) if latencies else None,
        latency_max_ms=round(latencies[-1], 1) if latencies else None,
    )
