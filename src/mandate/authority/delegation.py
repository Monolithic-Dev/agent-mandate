"""Delegation chains (AUTH-013, AUTH-014, AUTH-016). Pure functions."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from mandate.authority.ports import DelegationChain
from mandate.authority.scope import EffectiveScope, intersect
from mandate.models.domain import Delegation

MAX_CHAIN_DEPTH = 4


class Liveness(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    INACTIVE = "inactive"


def delegation_liveness(delegation: Delegation, as_of: int) -> Liveness:
    """Is this delegation in force at ``as_of``? Uses timestamps only (AUTH-008, AUTH-014)."""
    if delegation.created_at > as_of:
        return Liveness.INACTIVE
    if delegation.revoked_at is not None and delegation.revoked_at <= as_of:
        return Liveness.REVOKED
    if delegation.valid_from > as_of:
        return Liveness.INACTIVE
    if delegation.valid_to is not None and as_of >= delegation.valid_to:
        return Liveness.INACTIVE
    return Liveness.ACTIVE


def chain_liveness(hops: Sequence[Delegation], as_of: int) -> Liveness:
    """Revoked if any hop is revoked; inactive if any hop is not yet or no longer valid."""
    states = [delegation_liveness(hop, as_of) for hop in hops]
    if Liveness.REVOKED in states:
        return Liveness.REVOKED
    if Liveness.INACTIVE in states:
        return Liveness.INACTIVE
    return Liveness.ACTIVE


def is_well_formed(chain: DelegationChain, target_agent_id: str) -> bool:
    """Defensive check on what a store returns (AUTH-016): contiguous, bounded, no repeats."""
    hops = chain.hops
    if not hops or len(hops) > MAX_CHAIN_DEPTH:
        return False
    if hops[0].from_agent != chain.root_agent_id or hops[-1].to_agent != target_agent_id:
        return False
    for earlier, later in zip(hops, hops[1:], strict=False):
        if earlier.to_agent != later.from_agent:
            return False
    agents = [chain.root_agent_id, *(hop.to_agent for hop in hops)]
    return len(set(agents)) == len(agents)


def narrow(scope: EffectiveScope, hops: Sequence[Delegation]) -> EffectiveScope | None:
    """Narrow a delegator's scope by every delegation on the chain (AUTH-013)."""
    current: EffectiveScope | None = scope
    for hop in hops:
        if current is None:
            return None
        current = intersect(current, EffectiveScope.from_delegation(hop))
    return current
