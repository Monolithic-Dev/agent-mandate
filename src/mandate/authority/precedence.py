"""Precedence among applicable rules (AUTH-017). Pure and order-independent."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from mandate.models.domain import Effect

# On a tie in activation time: deny beats confirm beats allow.
EFFECT_RANK: dict[Effect, int] = {Effect.DENY: 0, Effect.CONFIRM: 1, Effect.ALLOW: 2}


def precedence_key(activated_at: int, effect: Effect, tiebreak: str) -> tuple[int, int, str]:
    """Sort key where the smallest key wins.

    Most recently activated first; then deny, confirm, allow; then ``tiebreak`` (an id) so
    the result never depends on input order.
    """
    return (-activated_at, EFFECT_RANK[effect], tiebreak)


def pick_winner[T](items: Iterable[T], key: Callable[[T], tuple[int, int, str]]) -> T | None:
    """Return the winning item, or None if there are none."""
    return min(items, key=key, default=None)
