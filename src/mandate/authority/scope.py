"""Scope matching and narrowing (AUTH-011, AUTH-012, AUTH-013). Pure functions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mandate.models.domain import Delegation, Scope
from mandate.models.registry import action_type_covers
from mandate.models.resources import resource_matches


class Applicability(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    CONSTRAINT_FAILED = "constraint_failed"


@dataclass(frozen=True)
class EffectiveScope:
    """What a rule covers once any delegation narrowing has been applied.

    ``resource_patterns`` are all required to match (a conjunction), because narrowing
    intersects the delegator's patterns with each delegation's pattern.
    """

    scope_id: str
    action_type: str
    resource_patterns: tuple[str, ...]
    max_amount: int | None = None

    @classmethod
    def from_scope(cls, scope: Scope) -> EffectiveScope:
        return cls(
            scope_id=scope.id,
            action_type=scope.action_type,
            resource_patterns=(scope.resource_pattern,),
            max_amount=scope.constraints.max_amount,
        )

    @classmethod
    def from_delegation(cls, delegation: Delegation) -> EffectiveScope:
        return cls(
            scope_id=delegation.id,
            action_type=delegation.action_type,
            resource_patterns=(delegation.resource_pattern,),
            max_amount=delegation.constraints.max_amount,
        )


def intersect_action_types(a: str, b: str) -> str | None:
    """The narrower of two action-type patterns, or None if they do not overlap."""
    if action_type_covers(a, b):
        return b
    if action_type_covers(b, a):
        return a
    return None


def intersect(a: EffectiveScope, b: EffectiveScope) -> EffectiveScope | None:
    """Narrow ``a`` by ``b`` (AUTH-013). Returns None when nothing remains."""
    action_type = intersect_action_types(a.action_type, b.action_type)
    if action_type is None:
        return None
    amounts = [m for m in (a.max_amount, b.max_amount) if m is not None]
    patterns = tuple(dict.fromkeys(a.resource_patterns + b.resource_patterns))
    return EffectiveScope(
        scope_id=a.scope_id,
        action_type=action_type,
        resource_patterns=patterns,
        max_amount=min(amounts) if amounts else None,
    )


def _amount_within(amount: Any, limit: int) -> bool:
    if isinstance(amount, bool) or not isinstance(amount, int | float):
        return False
    if not math.isfinite(amount) or amount < 0:
        return False
    return bool(amount <= limit)


def applicability(
    scope: EffectiveScope, action_type: str, resource: str, args: dict[str, Any]
) -> Applicability:
    """Does ``scope`` cover this concrete action? (AUTH-011, AUTH-012)."""
    if not action_type_covers(scope.action_type, action_type):
        return Applicability.NO_MATCH
    if not all(resource_matches(pattern, resource) for pattern in scope.resource_patterns):
        return Applicability.NO_MATCH
    if scope.max_amount is not None and not _amount_within(args.get("amount"), scope.max_amount):
        return Applicability.CONSTRAINT_FAILED
    return Applicability.MATCH
