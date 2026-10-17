import itertools

import pytest

from mandate.ids import ID_RE, PREFIXES, is_valid_id, new_id


def test_new_id_matches_regex() -> None:
    for prefix in sorted(PREFIXES):
        assert ID_RE.match(new_id(prefix))


def test_new_id_rejects_unknown_prefix() -> None:
    with pytest.raises(ValueError):
        new_id("zzz")


def test_ids_are_time_ordered() -> None:
    ids = [new_id("ins", now_ms=t, randbits=lambda _bits: 0) for t in (1, 2, 1000, 10**9, 10**12)]
    assert ids == sorted(ids)


def test_ids_unique_over_10000() -> None:
    ids = {new_id("dec", now_ms=1_760_500_000_000) for _ in range(10_000)}
    assert len(ids) == 10_000


def test_new_id_is_deterministic_with_injected_inputs() -> None:
    first = new_id("act", now_ms=5, randbits=lambda _bits: 123)
    second = new_id("act", now_ms=5, randbits=lambda _bits: 123)
    assert first == second


def test_timestamp_range_checked() -> None:
    with pytest.raises(ValueError):
        new_id("act", now_ms=-1)
    with pytest.raises(ValueError):
        new_id("act", now_ms=1 << 50)


def test_is_valid_id() -> None:
    value = new_id("ins")
    assert is_valid_id(value)
    assert is_valid_id(value, "ins")
    assert not is_valid_id(value, "dec")


@pytest.mark.parametrize(
    "bad",
    ["", "ins_", "ins_short", "xxx_01J9Z8Q4N7M3KX2V5T6R8W0YAB", "ins-01J9Z8Q4N7M3KX2V5T6R8W0YAB"],
)
def test_is_valid_id_rejects_malformed(bad: str) -> None:
    assert not is_valid_id(bad)


def test_injection_like_strings_are_not_valid_ids() -> None:
    for text in ("ins_' OR 1=1 --", "ins_}) MATCH (n) DETACH DELETE n //", "../etc/passwd"):
        assert not is_valid_id(text)


def test_all_prefixes_distinct_prefix_checks() -> None:
    for a, b in itertools.permutations(sorted(PREFIXES), 2):
        assert not is_valid_id(new_id(a), b)
