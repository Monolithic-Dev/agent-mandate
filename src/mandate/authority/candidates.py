"""Candidate selection: from stored records to the rules relevant to one check."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from mandate.authority.delegation import (
    MAX_CHAIN_DEPTH,
    Liveness,
    chain_liveness,
    is_well_formed,
    narrow,
)
from mandate.authority.lineage import LineageResult, compute_lineage
from mandate.authority.ports import AuthorityReader, InstructionRecord, Supersession
from mandate.authority.scope import Applicability, EffectiveScope, applicability
from mandate.models.domain import CheckRequest, Delegation, Instruction


class CandidateStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    INACTIVE = "inactive"  # pending, not yet valid, or expired
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Candidate:
    instruction: Instruction
    scope: EffectiveScope
    origin_agent_id: str  # the agent the instruction applies to (the chain root, if delegated)
    chain: tuple[Delegation, ...]
    applicability: Applicability
    lineage: LineageResult

    @property
    def key(self) -> str:
        """Stable identity: the same instruction can arrive through several chains."""
        return f"{self.instruction.id}|{'/'.join(d.id for d in self.chain)}"


@dataclass(frozen=True)
class Snapshot:
    """Everything the decision point needs, loaded once for one request."""

    agent_id: str
    candidates: tuple[Candidate, ...]
    supersessions: tuple[Supersession, ...]


def candidate_status(
    candidate: Candidate, as_of: int, superseded: frozenset[str] = frozenset()
) -> CandidateStatus:
    """Lifecycle state of a candidate at ``as_of`` (AUTH-007 to AUTH-010, AUTH-014)."""
    instruction = candidate.instruction
    if instruction.quarantined:
        return CandidateStatus.QUARANTINED
    if instruction.activated_at is None or instruction.activated_at > as_of:
        return CandidateStatus.INACTIVE
    if instruction.revoked_at is not None and instruction.revoked_at <= as_of:
        return CandidateStatus.REVOKED
    chain_state = chain_liveness(candidate.chain, as_of)
    if chain_state is Liveness.REVOKED:
        return CandidateStatus.REVOKED
    valid_from = (
        instruction.valid_from if instruction.valid_from is not None else instruction.activated_at
    )
    if valid_from > as_of:
        return CandidateStatus.INACTIVE
    if instruction.valid_to is not None and as_of >= instruction.valid_to:
        return CandidateStatus.INACTIVE
    if instruction.id in superseded:
        return CandidateStatus.SUPERSEDED
    if chain_state is Liveness.INACTIVE:
        return CandidateStatus.INACTIVE
    return CandidateStatus.ACTIVE


def superseded_ids(supersessions: Sequence[Supersession], as_of: int) -> frozenset[str]:
    """Instructions replaced by a non-quarantined superseder at or before ``as_of`` (AUTH-009)."""
    return frozenset(
        s.superseded_id for s in supersessions if s.at <= as_of and not s.by_quarantined
    )


def build_snapshot(reader: AuthorityReader, request: CheckRequest, as_of: int) -> Snapshot:
    """Load the candidates that could bear on ``request``.

    Candidates whose scope does not cover the action are dropped here, so lineage (the
    expensive part) is only computed for rules that matter.
    """
    records: dict[str, Sequence[InstructionRecord]] = {}
    lineage_cache: dict[str, LineageResult] = {}

    def records_for(agent_id: str) -> Sequence[InstructionRecord]:
        if agent_id not in records:
            records[agent_id] = reader.instructions_for_agent(agent_id, as_of)
        return records[agent_id]

    def lineage_for(instruction_id: str) -> LineageResult:
        if instruction_id not in lineage_cache:
            lineage_cache[instruction_id] = compute_lineage(reader, instruction_id)
        return lineage_cache[instruction_id]

    candidates: list[Candidate] = []

    def consider(record: InstructionRecord, hops: tuple[Delegation, ...]) -> None:
        scope = EffectiveScope.from_scope(record.scope)
        narrowed = narrow(scope, hops) if hops else scope
        if narrowed is None:
            return
        fit = applicability(narrowed, request.action_type, request.resource, request.args)
        if fit is Applicability.NO_MATCH:
            return
        candidates.append(
            Candidate(
                instruction=record.instruction,
                scope=narrowed,
                origin_agent_id=record.agent_id,
                chain=hops,
                applicability=fit,
                lineage=lineage_for(record.instruction.id),
            )
        )

    for record in records_for(request.agent_id):
        consider(record, ())
    for chain in reader.delegation_chains(request.agent_id, as_of, MAX_CHAIN_DEPTH):
        if not is_well_formed(chain, request.agent_id):
            continue
        for record in records_for(chain.root_agent_id):
            consider(record, chain.hops)

    ids = sorted({c.instruction.id for c in candidates})
    supersessions = tuple(reader.supersessions(ids, as_of)) if ids else ()
    return Snapshot(request.agent_id, tuple(candidates), supersessions)
