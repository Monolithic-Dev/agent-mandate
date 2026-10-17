"""The activity overview: buckets over the window, counts, and latency percentiles."""

from mandate.authority.ports import ActivityRow
from mandate.lineage.activity import bucket_size, percentile, summarise, window

HOUR = 3_600_000


def row(at: int, result: str = "allow", **extra: object) -> ActivityRow:
    base = {
        "reason": "authorized",
        "action_type": "email.read",
        "agent_id": "agt_a",
        "latency_ms": 5.0,
    }
    return ActivityRow(at=at, result=result, **(base | extra))  # type: ignore[arg-type]


def test_the_window_is_whole_buckets_ending_with_the_current_one() -> None:
    now = 100 * HOUR + 1_234
    since, until, size = window(now, 24)
    assert (size, until - since, until) == (HOUR, 24 * HOUR, 101 * HOUR)
    assert bucket_size(168) == 6 * HOUR and window(now, 168)[1] - window(now, 168)[0] == 168 * HOUR


def test_every_bucket_is_present_and_counts_by_result() -> None:
    now = 100 * HOUR + 10
    rows = [row(100 * HOUR + 5), row(100 * HOUR + 6, "deny", reason="no_authority_path"),
            row(99 * HOUR + 1, "confirm", reason="confirm_rule", action_type="email.delete"),
            row(50 * HOUR)]  # fmt: skip
    activity = summarise(rows, now=now, hours=24, truncated=False)
    assert len(activity.buckets) == 24
    last, before = activity.buckets[-1], activity.buckets[-2]
    assert (last.allow, last.deny, before.confirm) == (1, 1, 1)
    assert sum(b.allow + b.confirm + b.deny for b in activity.buckets) == 3  # 50h ago is outside
    assert activity.results == {"allow": 2, "confirm": 1, "deny": 1}
    assert activity.reasons[0].key == "authorized" and activity.reasons[0].count == 2
    assert {c.key for c in activity.actions} == {"email.read", "email.delete"}


def test_latency_percentiles() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.5) == 50 and percentile(values, 0.95) == 95
    rows = [row(HOUR, latency_ms=v) for v in values]
    activity = summarise(rows, now=HOUR, hours=1, truncated=True)
    assert (activity.latency_p50_ms, activity.latency_p95_ms, activity.latency_max_ms) == (
        50,
        95,
        100,
    )
    assert activity.truncated
    empty = summarise([], now=HOUR, hours=1, truncated=False)
    assert empty.latency_p50_ms is None and empty.total == 0
