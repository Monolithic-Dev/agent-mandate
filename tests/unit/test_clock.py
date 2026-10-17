import pytest

from mandate.clock import SCENARIO_T0_MS, FixedClock, SystemClock


def test_fixed_clock_starts_at_scenario_t0() -> None:
    assert FixedClock().now_ms() == SCENARIO_T0_MS


def test_fixed_clock_advances_and_sets() -> None:
    clock = FixedClock(10)
    assert clock.advance(5) == 15
    clock.set(100)
    assert clock.now_ms() == 100


def test_fixed_clock_cannot_go_backwards() -> None:
    clock = FixedClock(10)
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_fixed_clock_rejects_negative_start() -> None:
    with pytest.raises(ValueError):
        FixedClock(-1)


def test_system_clock_is_monotonic_enough() -> None:
    clock = SystemClock()
    first = clock.now_ms()
    second = clock.now_ms()
    assert second >= first
    assert first > 1_700_000_000_000
