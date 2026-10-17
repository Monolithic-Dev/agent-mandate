"""What if the owner said this? A preview of a sentence before it becomes authority.

Nothing live is written. The preview reports:

* the rules the sentence would make (with any time limit, and which need confirmation),
* the clauses the parser did not understand,
* the active rules they would contradict, duplicate or re-limit, and
* what would change: recent requests are re-checked now, once against the live rules and
  once against a throwaway copy of the tenant's graph where the sentence has been said and
  confirmed. Every request whose answer differs is listed.

The copy is the same one replay uses (``clone_for_replay``: ``GRAPH.COPY`` in FalkorDB) and
is always removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mandate.authority.check import check_authority
from mandate.authority.parser import ParsedInstruction, parse_utterance
from mandate.authority.ports import AuthorityStore, InstructionRecord
from mandate.authority.scope import intersect_action_types
from mandate.authority.service import AuthorityService
from mandate.clock import Clock
from mandate.errors import NotOwner, ValidationFailure
from mandate.models.domain import (
    AgentKind,
    Channel,
    CheckRequest,
    Effect,
    InstructionStatus,
    Reason,
    Result,
    Role,
)
from mandate.models.resources import resource_matches

SAMPLE_DECISIONS = 200  # how far back the preview looks for requests to re-check


@dataclass(frozen=True)
class PreviewRule:
    effect: Effect
    action_type: str
    resource_pattern: str
    max_amount: int | None
    valid_for_ms: int | None
    valid_to: int | None
    needs_confirmation: bool
    text_span: str


@dataclass(frozen=True)
class RuleConflict:
    rule: int  # index into ``Preview.rules``
    instruction_id: str
    text_span: str
    effect: Effect
    action_type: str
    resource_pattern: str
    max_amount: int | None
    # contradicts: a different effect over the same ground (the new rule wins where both
    # apply, being newer); duplicates: the same rule again (it replaces the old one);
    # changes_limit: the same allow with a different amount limit.
    kind: str


@dataclass(frozen=True)
class ImpactChange:
    agent_id: str
    action_type: str
    resource: str
    amount: Any
    example_decision_id: str
    was_result: Result
    was_reason: Reason
    now_result: Result
    now_reason: Reason
    result_changed: bool  # False when only the reason differs (still denied, but why changed)


@dataclass(frozen=True)
class Preview:
    agent_ids: list[str]
    rules: list[PreviewRule] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    conflicts: list[RuleConflict] = field(default_factory=list)
    evaluated: int = 0
    changes: list[ImpactChange] = field(default_factory=list)


def _patterns_overlap(a: str, b: str) -> bool:
    return (
        a == b
        or resource_matches(a, b.replace("*", "x"))
        or resource_matches(b, a.replace("*", "x"))
    )


def _live_rules(store: AuthorityStore, agent_ids: set[str], now: int) -> list[InstructionRecord]:
    seen: set[str] = set()
    live: list[InstructionRecord] = []
    for record in store.list_instructions(status=InstructionStatus.ACTIVE.value):
        rule = record.instruction
        if record.agent_id not in agent_ids or rule.id in seen or rule.quarantined:
            continue
        if rule.valid_to is not None and now >= rule.valid_to:
            continue
        seen.add(rule.id)
        live.append(record)
    return live


def _conflicts(
    parsed: list[ParsedInstruction], live: list[InstructionRecord]
) -> list[RuleConflict]:
    found: list[RuleConflict] = []
    for index, new in enumerate(parsed):
        for record in live:
            scope = record.scope
            if intersect_action_types(new.action_type, scope.action_type) is None:
                continue
            if not _patterns_overlap(new.resource_pattern, scope.resource_pattern):
                continue
            old_amount = scope.constraints.max_amount
            new_amount = new.constraints.max_amount
            if new.effect is not record.instruction.effect:
                kind = "contradicts"
            elif old_amount != new_amount:
                kind = "changes_limit"
            else:
                kind = "duplicates"
            found.append(
                RuleConflict(
                    rule=index,
                    instruction_id=record.instruction.id,
                    text_span=record.instruction.text_span,
                    effect=record.instruction.effect,
                    action_type=scope.action_type,
                    resource_pattern=scope.resource_pattern,
                    max_amount=old_amount,
                    kind=kind,
                )
            )
    return found


def preview_utterance(
    store: AuthorityStore,
    clock: Clock,
    *,
    principal_id: str,
    text: str,
    agent_ids: list[str] | None = None,
    sample: int = SAMPLE_DECISIONS,
) -> Preview:
    """What saying (and confirming) ``text`` as the owner would do. Writes nothing live."""
    principal = store.get_principal(principal_id)
    if principal.role is not Role.OWNER:
        raise NotOwner("only the owner's words become rules; preview as the owner")
    targets = agent_ids or [a.id for a in store.list_agents() if a.kind is AgentKind.PRIMARY]
    if not targets:
        raise ValidationFailure("there is no primary agent to apply rules to")
    for agent_id in targets:
        store.get_agent(agent_id)  # NotFound for an agent of another tenant

    now = clock.now_ms()
    parsed = parse_utterance(text)
    preview = Preview(
        agent_ids=list(targets),
        rules=[
            PreviewRule(
                effect=item.effect,
                action_type=item.action_type,
                resource_pattern=item.resource_pattern,
                max_amount=item.constraints.max_amount,
                valid_for_ms=item.valid_for_ms,
                valid_to=now + item.valid_for_ms if item.valid_for_ms else None,
                needs_confirmation=item.requires_confirmation,
                text_span=item.text_span,
            )
            for item in parsed.instructions
        ],
        unparsed=list(parsed.unparsed),
    )
    if not parsed.instructions:
        return preview
    preview.conflicts.extend(_conflicts(parsed.instructions, _live_rules(store, set(targets), now)))

    # Requests worth re-checking: recent ones, by these agents, for actions these rules touch.
    touched = [item.action_type for item in parsed.instructions]
    requests: dict[tuple[str, str, str, str], tuple[CheckRequest, str]] = {}
    for row in store.list_decisions(limit=sample):
        action = row.action
        if row.agent_id not in targets:
            continue
        if not any(intersect_action_types(t, action.action_type) for t in touched):
            continue
        args = {k: v for k, v in action.args.items() if k == "amount"}
        key = (row.agent_id, action.action_type, action.resource, repr(args.get("amount")))
        if key not in requests:
            requests[key] = (
                CheckRequest(
                    agent_id=row.agent_id,
                    action_type=action.action_type,
                    resource=action.resource,
                    args=args,
                    # No as_of: each check is at the moment it runs, so a rule said on the copy
                    # an instant after the preview began already applies to the "after" check.
                ),
                row.decision.id,
            )
    if not requests:
        return preview

    before = {
        key: check_authority(store, None, req, clock=clock, persist=False).decision
        for key, (req, _) in requests.items()
    }
    changes: list[ImpactChange] = []
    with store.clone_for_replay() as clone:
        service = AuthorityService(clone, clock)
        said = service.ingest_utterance(
            principal_id=principal_id, text=text, channel=Channel.OWNER_DIRECT, agent_ids=targets
        )
        for item in said.instructions:
            if item.needs_confirmation:
                service.confirm_instruction(item.instruction.id, principal_id)
        for key, (req, example) in requests.items():
            after = check_authority(clone, None, req, clock=clock, persist=False).decision
            was = before[key]
            if (after.result, after.reason) != (was.result, was.reason):
                changes.append(
                    ImpactChange(
                        agent_id=req.agent_id,
                        action_type=req.action_type,
                        resource=req.resource,
                        amount=req.args.get("amount"),
                        example_decision_id=example,
                        was_result=was.result,
                        was_reason=was.reason,
                        now_result=after.result,
                        now_reason=after.reason,
                        result_changed=after.result is not was.result,
                    )
                )
    changes.sort(key=lambda c: not c.result_changed)  # flipped answers first
    return Preview(
        agent_ids=preview.agent_ids,
        rules=preview.rules,
        unparsed=preview.unparsed,
        conflicts=preview.conflicts,
        evaluated=len(requests),
        changes=changes,
    )
