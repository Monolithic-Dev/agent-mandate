import random
from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from mandate.authority.precedence import EFFECT_RANK, pick_winner, precedence_key
from mandate.models.domain import Effect


@dataclass(frozen=True)
class Rule:
    id: str
    activated_at: int
    effect: Effect


def key(rule: Rule) -> tuple[int, int, str]:
    return precedence_key(rule.activated_at, rule.effect, rule.id)


def test_no_candidates() -> None:
    assert pick_winner([], key) is None


def test_most_recent_wins() -> None:
    older = Rule("a", 100, Effect.DENY)
    newer = Rule("b", 200, Effect.ALLOW)
    assert pick_winner([older, newer], key) == newer


def test_tie_deny_beats_confirm_beats_allow() -> None:
    allow, confirm, deny = (
        Rule(e.value, 100, e) for e in (Effect.ALLOW, Effect.CONFIRM, Effect.DENY)
    )
    assert pick_winner([allow, confirm, deny], key) == deny
    assert pick_winner([allow, confirm], key) == confirm


def test_effect_rank_is_total_and_deny_first() -> None:
    assert sorted(EFFECT_RANK, key=EFFECT_RANK.__getitem__) == [
        Effect.DENY,
        Effect.CONFIRM,
        Effect.ALLOW,
    ]


def test_later_narrow_allow_beats_earlier_broad_deny_by_recency() -> None:
    broad_deny = Rule("deny", 100, Effect.DENY)
    narrow_allow = Rule("allow", 200, Effect.ALLOW)
    assert pick_winner([broad_deny, narrow_allow], key) == narrow_allow


def test_later_broad_deny_beats_earlier_narrow_allow_by_recency() -> None:
    narrow_allow = Rule("allow", 100, Effect.ALLOW)
    broad_deny = Rule("deny", 200, Effect.DENY)
    assert pick_winner([narrow_allow, broad_deny], key) == broad_deny


rules = st.lists(
    st.builds(
        Rule,
        id=st.text(alphabet="abcdef", min_size=1, max_size=3),
        activated_at=st.integers(min_value=0, max_value=5),
        effect=st.sampled_from(list(Effect)),
    ),
    min_size=1,
    max_size=8,
    unique_by=lambda r: r.id,
)


@given(items=rules, seed=st.integers())
def test_auth017_order_independent(items: list[Rule], seed: int) -> None:
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    assert pick_winner(items, key) == pick_winner(shuffled, key)
