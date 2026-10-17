"""Reliance ranking: which rules the recorded decisions leaned on, and which deserve a look.

Blast radius answers "what did this one rule touch?". Reliance answers the opposite question
before anything is known to be wrong: across everything the gateway has decided, which rules
carry the most weight, and are any of the heavy ones shaky? A rule is flagged when it

* has a **mixed origin** (it traces partly to untrusted content, so it was never fully the
  owner's own word),
* has an **untrusted origin** yet still decided something (this should never happen; a hit is
  a bug worth knowing about),
* is **quarantined** but past decisions still used it, or
* grants a **high-impact** action (it lets agents delete, send or refund).

Informational flags: ``revoked``, ``grants_high_impact``, and ``auto_activated`` (a low-impact
rule that took effect when the owner said it, without a separate confirmation). Rules
activated before activation was audited carry no ``auto_activated`` flag either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from mandate.authority.ports import AuthorityStore, InstructionRecord
from mandate.models.domain import ActivationKind, Effect, InstructionStatus, LineageTrust
from mandate.models.registry import HIGH_IMPACT

REVIEW_FLAGS = frozenset({"mixed_origin", "untrusted_origin", "quarantined"})


@dataclass(frozen=True)
class RelianceRow:
    instruction_id: str
    text_span: str
    effect: str
    action_type: str
    resource_pattern: str
    status: str
    lineage_trust: str
    decisions: int
    as_winner: int
    agents: int
    first_at: int
    last_at: int
    flags: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return bool(REVIEW_FLAGS & set(self.flags))


def _flags(record: InstructionRecord) -> tuple[str, ...]:
    instruction, scope = record.instruction, record.scope
    flags: list[str] = []
    if instruction.lineage_trust is LineageTrust.MIXED:
        flags.append("mixed_origin")
    if instruction.lineage_trust is LineageTrust.UNTRUSTED:
        flags.append("untrusted_origin")
    if instruction.quarantined:
        flags.append("quarantined")
    if instruction.status is InstructionStatus.REVOKED:
        flags.append("revoked")
    if instruction.effect is Effect.ALLOW and scope.action_type in HIGH_IMPACT:
        flags.append("grants_high_impact")
    if instruction.activated_via is ActivationKind.AUTO:
        flags.append("auto_activated")
    return tuple(flags)


def rank_reliance(store: AuthorityStore, limit: int = 20) -> list[RelianceRow]:
    """The most relied-on instructions, heaviest first, with review flags."""
    counts = store.reliance_counts(limit)
    records: dict[str, InstructionRecord] = {}
    for record in store.list_instructions():
        records.setdefault(record.instruction.id, record)
    rows: list[RelianceRow] = []
    for count in counts:
        found = records.get(count.instruction_id)
        if found is None:
            continue  # decided on a rule that no longer lists; nothing to show
        instruction, scope = found.instruction, found.scope
        rows.append(
            RelianceRow(
                instruction_id=count.instruction_id,
                text_span=instruction.text_span,
                effect=instruction.effect.value,
                action_type=scope.action_type,
                resource_pattern=scope.resource_pattern,
                status=instruction.status.value,
                lineage_trust=instruction.lineage_trust.value,
                decisions=count.decisions,
                as_winner=count.as_winner,
                agents=count.agents,
                first_at=count.first_at,
                last_at=count.last_at,
                flags=_flags(found),
            )
        )
    return rows
