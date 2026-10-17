"""An in-memory implementation of the authority ports, for fast unit tests.

It implements the same ``AuthorityStore`` protocol as the FalkorDB adapter (so the service
can be tested without a database) and offers builder methods (``say``, ``rule``,
``delegate`` ...) so tests read like the scenarios in docs/scenarios.md. The contract
tests hold it to the same behaviour as the real store.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from mandate.authority.lineage import compute_lineage
from mandate.authority.ports import (
    ActivityRow,
    ChangeMarker,
    DecisionSummary,
    DelegationChain,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    InstructionRecord,
    LineageNode,
    RecordedDecision,
    RelianceCount,
    StoredAction,
    Supersession,
    UsedInstruction,
    keep_nodes,
    rules_digest,
)
from mandate.clock import FixedClock
from mandate.errors import AlreadyActive, Conflict, NotFound, UntrustedLineage, ValidationFailure
from mandate.ids import new_id
from mandate.models.domain import (
    Action,
    ActionStatus,
    ActivationKind,
    Agent,
    AgentKind,
    Approval,
    Channel,
    Constraints,
    Decision,
    Delegation,
    Effect,
    Instruction,
    InstructionStatus,
    LineageTrust,
    Principal,
    Role,
    Scope,
    Summary,
    TokenRevocation,
    Utterance,
)
from mandate.models.trust import compute_trust


@dataclass
class _Rule:
    instruction: Instruction
    scope: Scope
    agent_ids: list[str]
    expressed_by: list[str]


@dataclass
class InMemoryStore:
    clock: FixedClock = field(default_factory=FixedClock)
    principals: dict[str, Principal] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)
    utterances: dict[str, Utterance] = field(default_factory=dict)
    speakers: dict[str, str] = field(default_factory=dict)
    summaries: dict[str, Summary] = field(default_factory=dict)
    derived_from: dict[str, list[str]] = field(default_factory=dict)
    rules: dict[str, _Rule] = field(default_factory=dict)
    delegations: dict[str, Delegation] = field(default_factory=dict)
    supersession_log: list[tuple[str, str, int]] = field(default_factory=list)
    recorded: list[tuple[Action, Decision, list[UsedInstruction], str]] = field(
        default_factory=list
    )
    action_status: dict[str, ActionStatus] = field(default_factory=dict)
    approvals: list[tuple[Approval, str]] = field(default_factory=list)
    revoked_tokens: dict[str, TokenRevocation] = field(default_factory=dict)
    fail_reads: Exception | None = None
    fail_record: Exception | None = None

    # --- AuthorityWriter ----------------------------------------------------------

    def create_principal(self, principal: Principal) -> Principal:
        self.principals[principal.id] = principal
        return principal

    def create_agent(self, agent: Agent) -> Agent:
        self.agents[agent.id] = agent
        return agent

    def create_utterance(self, utterance: Utterance, speaker_id: str) -> Utterance:
        if speaker_id not in self.principals:
            raise NotFound("no such principal")
        self.utterances[utterance.id] = utterance
        self.speakers[utterance.id] = speaker_id
        return utterance

    def create_summary(self, summary: Summary, derived_from: Sequence[str]) -> Summary:
        for source in derived_from:
            if source not in {*self.utterances, *self.summaries, *self.rules}:
                raise NotFound(f"no such source: {source!r}")
        self.summaries[summary.id] = summary
        self.derived_from[summary.id] = list(derived_from)
        return summary

    def create_instruction(
        self,
        *,
        source_id: str,
        effect: Effect,
        action_type: str,
        agent_ids: Sequence[str],
        created_at: int,
        text_span: str,
        resource_pattern: str = "*",
        max_amount: int | None = None,
        valid_from: int | None = None,
        valid_to: int | None = None,
        instruction_id: str | None = None,
    ) -> Instruction:
        if not agent_ids:
            raise ValidationFailure("an instruction must apply to at least one agent")
        if source_id not in self.utterances and source_id not in self.summaries:
            raise NotFound("source not found")
        unknown = set(agent_ids) - set(self.agents)
        if unknown:
            raise NotFound(f"unknown agents: {sorted(unknown)}")
        rule_id = instruction_id or new_id("ins", now_ms=created_at)
        scope = Scope(
            id=new_id("scp"),
            action_type=action_type,
            resource_pattern=resource_pattern,
            constraints=Constraints(max_amount=max_amount),
        )
        placeholder = Instruction.model_construct(id=rule_id)  # only to compute lineage
        record = _Rule(placeholder, scope, list(agent_ids), [source_id])
        self.rules[rule_id] = record
        trust = compute_lineage(self, rule_id).trust
        record.instruction = Instruction(
            id=rule_id,
            effect=effect,
            text_span=text_span,
            status=InstructionStatus.PENDING,
            created_at=created_at,
            valid_from=valid_from,
            valid_to=valid_to,
            lineage_trust=trust,
        )
        return record.instruction

    def get_instruction(self, instruction_id: str) -> Instruction:
        if instruction_id not in self.rules:
            raise NotFound("no such instruction")
        return self.rules[instruction_id].instruction

    def activate_instruction(
        self,
        instruction_id: str,
        at: int,
        *,
        by: str | None = None,
        via: ActivationKind | None = None,
    ) -> Instruction:
        current = self.get_instruction(instruction_id)
        trust = compute_lineage(self, instruction_id).trust
        if trust is LineageTrust.UNTRUSTED:
            raise UntrustedLineage("this instruction has no trusted origin")
        if current.status is not InstructionStatus.PENDING:
            raise AlreadyActive(f"instruction is {current.status.value}, not pending")
        return self._set(
            instruction_id,
            status=InstructionStatus.ACTIVE,
            activated_at=at,
            valid_from=current.valid_from if current.valid_from is not None else at,
            lineage_trust=trust,
            activated_by=by,
            activated_via=via,
        )

    def revoke_instruction(
        self, instruction_id: str, at: int, *, by: str | None = None
    ) -> Instruction:
        current = self.get_instruction(instruction_id)
        if current.revoked_at is not None:
            raise Conflict("instruction is already revoked")
        return self._set(
            instruction_id, revoked_at=at, status=InstructionStatus.REVOKED, revoked_by=by
        )

    def set_quarantined(
        self,
        instruction_ids: Sequence[str],
        value: bool,
        *,
        at: int | None = None,
        by: str | None = None,
    ) -> int:
        changed = 0
        for instruction_id in instruction_ids:
            if instruction_id in self.rules:
                self._set(
                    instruction_id,
                    quarantined=value,
                    quarantine_changed_at=at,
                    quarantine_changed_by=by,
                )
                changed += 1
        return changed

    def supersede(
        self,
        new_instruction: Instruction | str,
        old_instruction: Instruction | str,
        at: int | None = None,
    ) -> None:
        """Accepts ids (the port form) or instructions (the builder form)."""
        new_id_ = new_instruction if isinstance(new_instruction, str) else new_instruction.id
        old_id = old_instruction if isinstance(old_instruction, str) else old_instruction.id
        if new_id_ not in self.rules or old_id not in self.rules:
            raise NotFound("both instructions must exist to record a supersession")
        self.supersession_log.append((new_id_, old_id, self._at(at)))
        if self.rules[old_id].instruction.status is InstructionStatus.ACTIVE:
            self._set(old_id, status=InstructionStatus.SUPERSEDED)

    def create_delegation(self, delegation: Delegation) -> Delegation:
        if delegation.from_agent not in self.agents or delegation.to_agent not in self.agents:
            raise NotFound("both agents must exist to create a delegation")
        self.delegations[delegation.id] = delegation
        return delegation

    def revoke_delegation(self, delegation: Delegation | str, at: int | None = None) -> Delegation:
        """Port form (an id) raises ``Conflict`` if already revoked; the builder form (a
        ``Delegation``) keeps the first revocation instead."""
        delegation_id = delegation if isinstance(delegation, str) else delegation.id
        current = self.delegations.get(delegation_id)
        if current is None:
            raise Conflict("delegation is unknown or already revoked")
        if current.revoked_at is not None:
            if isinstance(delegation, str):
                raise Conflict("delegation is unknown or already revoked")
            return current
        updated = current.model_copy(update={"revoked_at": self._at(at)})
        self.delegations[delegation_id] = updated
        return updated

    def set_action_status(self, action_id: str, status: ActionStatus) -> None:
        if not any(action.id == action_id for action, *_ in self.recorded):
            raise NotFound("no such action")
        self.action_status[action_id] = status

    def resolve_pending_action(
        self, action_id: str, approval: Approval, new_status: ActionStatus
    ) -> bool:
        stored = self.get_action(action_id)
        if stored.action.status is not ActionStatus.PENDING:
            return False
        self.action_status[action_id] = new_status
        self.approvals.append((approval, action_id))
        return True

    def revoke_token(self, revocation: TokenRevocation) -> TokenRevocation:
        return self.revoked_tokens.setdefault(revocation.token_id, revocation)

    def token_revoked(self, token_id: str) -> bool:
        return token_id in self.revoked_tokens

    def change_marker(self) -> ChangeMarker:
        pending = self.list_actions(status=ActionStatus.PENDING, limit=10**6)
        rules = [r.instruction for r in self.rules.values()]
        return ChangeMarker(
            decisions=len(self.recorded),
            last_decision_at=max((d.at for _a, d, _u, _g in self.recorded), default=None),
            pending=tuple(sorted(r.action.id for r in pending)),
            rules=rules_digest(
                [i.id, i.status.value, i.quarantined, i.lineage_trust.value] for i in rules
            ),
        )

    def list_token_revocations(self, limit: int = 100) -> list[TokenRevocation]:
        rows = sorted(
            self.revoked_tokens.values(), key=lambda r: (r.revoked_at, r.token_id), reverse=True
        )
        return rows[:limit]

    def _set(self, instruction_id: str, **changes: object) -> Instruction:
        rule = self.rules[instruction_id]
        rule.instruction = rule.instruction.model_copy(update=changes)
        return rule.instruction

    # --- AuthorityLookup ----------------------------------------------------------

    def get_principal(self, principal_id: str) -> Principal:
        if principal_id not in self.principals:
            raise NotFound("no such principal")
        return self.principals[principal_id]

    def get_agent(self, agent_id: str) -> Agent:
        if agent_id not in self.agents:
            raise NotFound("no such agent")
        return self.agents[agent_id]

    def list_agents(self) -> list[Agent]:
        return sorted(self.agents.values(), key=lambda a: a.id)

    def list_principals(self) -> list[Principal]:
        return sorted(self.principals.values(), key=lambda p: p.id)

    def list_instructions(
        self, *, status: str | None = None, agent_id: str | None = None
    ) -> list[InstructionRecord]:
        records = [
            InstructionRecord(rule.instruction, rule.scope, agent)
            for rule in self.rules.values()
            for agent in rule.agent_ids
            if (status is None or rule.instruction.status.value == status)
            and (agent_id is None or agent == agent_id)
        ]
        return sorted(records, key=lambda r: (r.instruction.created_at, r.instruction.id))

    def list_decisions(
        self, *, agent_id: str | None = None, limit: int = 50
    ) -> list[DecisionSummary]:
        rows = [
            DecisionSummary(decision, self.get_action(action.id).action, agent)
            for action, decision, _used, agent in self.recorded
            if agent_id is None or agent == agent_id
        ]
        rows.sort(key=lambda r: (r.decision.at, r.decision.id), reverse=True)
        return rows[:limit]

    def decision_activity(self, since: int, limit: int) -> list[ActivityRow]:
        rows = [
            ActivityRow(
                at=decision.at,
                result=decision.result.value,
                reason=decision.reason.value,
                action_type=action.action_type,
                agent_id=agent,
                latency_ms=decision.latency_ms,
            )
            for action, decision, _used, agent in self.recorded
            if decision.at >= since
        ]
        rows.sort(key=lambda r: r.at, reverse=True)
        return rows[:limit]

    def list_actions(
        self, *, status: ActionStatus | None = None, limit: int = 50
    ) -> list[StoredAction]:
        rows = [self.get_action(action.id) for action, _d, _u, _a in self.recorded]
        rows = [r for r in rows if status is None or r.action.status is status]
        rows.sort(key=lambda r: (r.action.at, r.action.id), reverse=True)
        return rows[:limit]

    def graph_snapshot(self, limit: int = 500) -> GraphSnapshot:
        """The same nodes and edges the FalkorDB store holds (data-model.md section 4)."""
        found: dict[str, GraphNode] = {}

        def add(label: str, model: Any) -> None:
            found.setdefault(model.id, GraphNode(model.id, label, model.model_dump(mode="json")))

        for principal in self.principals.values():
            add("Principal", principal)
        for agent in self.agents.values():
            add("Agent", agent)
        for utterance in self.utterances.values():
            add("Utterance", utterance)
        for summary in self.summaries.values():
            add("Summary", summary)
        for rule in self.rules.values():
            add("Instruction", rule.instruction)
            add("Scope", rule.scope)
        for action, decision, _used, _agent in self.recorded:
            add("Action", self.get_action(action.id).action)
            add("Decision", decision)
        for approval, _action_id in self.approvals:
            add("Approval", approval)

        kept, truncated = keep_nodes(list(found.values()), limit)
        ids = {node.id for node in kept}
        edges: list[GraphEdge] = []

        def link(source: str, target: str, kind: str, **props: Any) -> None:
            if source in ids and target in ids:
                edges.append(GraphEdge(source, target, kind, props))

        for utterance_id, speaker in self.speakers.items():
            link(speaker, utterance_id, "SAID")
        for summary_id, sources in self.derived_from.items():
            for source in sources:
                link(summary_id, source, "DERIVED_FROM")
        for rule in self.rules.values():
            for source in rule.expressed_by:
                link(source, rule.instruction.id, "EXPRESSES")
            link(rule.instruction.id, rule.scope.id, "ABOUT")
            for agent_id in rule.agent_ids:
                link(rule.instruction.id, agent_id, "APPLIES_TO")
        for new, old, at in self.supersession_log:
            link(new, old, "SUPERSEDES", at=at)
        for delegation in self.delegations.values():
            link(
                delegation.from_agent,
                delegation.to_agent,
                "DELEGATES_TO",
                id=delegation.id,
                action_type=delegation.action_type,
                resource_pattern=delegation.resource_pattern,
                revoked_at=delegation.revoked_at,
            )
        for action, decision, used, agent_id in self.recorded:
            link(action.id, agent_id, "PROPOSED_BY")
            link(decision.id, action.id, "CHECKED")
            for item in used:
                link(decision.id, item.instruction_id, "USED", role=item.role)
        for approval, action_id in self.approvals:
            link(approval.id, action_id, "APPROVES")
        return GraphSnapshot(kept, edges, truncated)

    def get_action(self, action_id: str) -> StoredAction:
        for action, decision, _used, agent_id in self.recorded:
            if action.id == action_id:
                status = self.action_status.get(action_id, action.status)
                return StoredAction(
                    action.model_copy(update={"status": status}), agent_id, decision.id
                )
        raise NotFound("no such action")

    def get_decision(self, decision_id: str) -> RecordedDecision:
        for action, decision, used, agent in self.recorded:
            if decision.id == decision_id:
                return RecordedDecision(decision, action, list(used), agent)
        raise NotFound("no such decision")

    # --- LineageReader ------------------------------------------------------------

    def derivation_step(self, instruction_ids: Sequence[str]) -> tuple[list[str], list[str]]:
        wanted = set(instruction_ids)
        summaries = sorted(
            sid for sid, sources in self.derived_from.items() if wanted & set(sources)
        )
        derived = sorted(
            rid
            for rid, rule in self.rules.items()
            if any(src in summaries for src in rule.expressed_by)
        )
        return summaries, derived

    def decisions_using(self, instruction_ids: Sequence[str]) -> list[DecisionSummary]:
        wanted = set(instruction_ids)
        rows = [
            DecisionSummary(decision, self.get_action(action.id).action, agent)
            for action, decision, used, agent in self.recorded
            if wanted & {u.instruction_id for u in used}
        ]
        return sorted(rows, key=lambda r: (r.decision.at, r.decision.as_of, r.decision.id))

    def reliance_counts(self, limit: int = 20) -> list[RelianceCount]:
        grouped: dict[str, list[tuple[Any, str, str]]] = {}
        for _action, decision, used, agent in self.recorded:
            for item in used:
                grouped.setdefault(item.instruction_id, []).append((decision, item.role, agent))
        rows = [
            RelianceCount(
                instruction_id,
                len({d.id for d, _, _ in uses}),
                len({d.id for d, role, _ in uses if role == "winner"}),
                len({agent for _, _, agent in uses}),
                min(d.at for d, _, _ in uses),
                max(d.at for d, _, _ in uses),
            )
            for instruction_id, uses in grouped.items()
        ]
        rows.sort(key=lambda r: (-r.decisions, r.instruction_id))
        return rows[: max(1, limit)]

    def delegations_via(self, instruction_ids: Sequence[str]) -> list[str]:
        wanted = set(instruction_ids)
        return sorted(d.id for d in self.delegations.values() if d.via_instruction in wanted)

    @contextmanager
    def clone_for_replay(self) -> Iterator[InMemoryStore]:
        yield copy.deepcopy(self)

    # --- builders used by tests ---------------------------------------------------

    def _at(self, at: int | None) -> int:
        return self.clock.now_ms() if at is None else at

    def add_principal(self, name: str, role: Role) -> Principal:
        return self.create_principal(Principal(id=new_id("prn"), name=name, role=role))

    def add_agent(self, name: str, kind: AgentKind = AgentKind.PRIMARY) -> Agent:
        return self.create_agent(Agent(id=new_id("agt"), name=name, kind=kind))

    def say(
        self,
        principal: Principal,
        text: str,
        channel: Channel = Channel.OWNER_DIRECT,
        at: int | None = None,
    ) -> Utterance:
        utterance = Utterance(
            id=new_id("utt"),
            text=text,
            channel=channel,
            trust=compute_trust(channel, principal.role),
            at=self._at(at),
        )
        return self.create_utterance(utterance, principal.id)

    def summarise(self, *sources: str, text: str = "summary", at: int | None = None) -> Summary:
        return self.create_summary(
            Summary(id=new_id("sum"), text=text, at=self._at(at)), list(sources)
        )

    def rule(
        self,
        source: Utterance | Summary,
        effect: Effect,
        action_type: str,
        *,
        resource_pattern: str = "*",
        agents: Sequence[Agent],
        max_amount: int | None = None,
        at: int | None = None,
        activate: bool = True,
        valid_from: int | None = None,
        valid_to: int | None = None,
        force_active: bool = False,
        text_span: str = "rule",
    ) -> Instruction:
        """Create an instruction and (optionally) activate it.

        ``force_active`` activates it even if its lineage is untrusted, simulating tampered
        data for defence-in-depth tests; the store itself would refuse (AUTH-006).
        """
        created = self._at(at)
        instruction = self.create_instruction(
            source_id=source.id,
            effect=effect,
            action_type=action_type,
            agent_ids=[agent.id for agent in agents],
            created_at=created,
            text_span=text_span,
            resource_pattern=resource_pattern,
            max_amount=max_amount,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        untrusted = instruction.lineage_trust is LineageTrust.UNTRUSTED
        if activate and not untrusted:
            return self.activate_instruction(instruction.id, created)
        if activate and untrusted and force_active:
            return self._set(
                instruction.id,
                status=InstructionStatus.ACTIVE,
                activated_at=created,
                valid_from=valid_from if valid_from is not None else created,
            )
        return instruction

    def revoke(self, instruction: Instruction, at: int | None = None) -> Instruction:
        try:
            return self.revoke_instruction(instruction.id, self._at(at))
        except Conflict:
            return self.get_instruction(instruction.id)  # keep the first revocation

    def quarantine(self, instruction: Instruction, value: bool = True) -> Instruction:
        self.set_quarantined([instruction.id], value)
        return self.get_instruction(instruction.id)

    def delegate(
        self,
        from_agent: Agent,
        to_agent: Agent,
        action_type: str,
        *,
        resource_pattern: str = "*",
        max_amount: int | None = None,
        at: int | None = None,
        valid_to: int | None = None,
    ) -> Delegation:
        created = self._at(at)
        return self.create_delegation(
            Delegation(
                id=new_id("dlg"),
                from_agent=from_agent.id,
                to_agent=to_agent.id,
                action_type=action_type,
                resource_pattern=resource_pattern,
                constraints=Constraints(max_amount=max_amount),
                created_at=created,
                valid_from=created,
                valid_to=valid_to,
            )
        )

    # --- AuthorityReader ----------------------------------------------------------

    def _maybe_fail(self) -> None:
        if self.fail_reads is not None:
            raise self.fail_reads

    def instructions_for_agent(self, agent_id: str, as_of: int) -> list[InstructionRecord]:
        self._maybe_fail()
        return [
            InstructionRecord(rule.instruction, rule.scope, agent_id)
            for rule in self.rules.values()
            if agent_id in rule.agent_ids and rule.instruction.created_at <= as_of
        ]

    def delegation_chains(self, agent_id: str, as_of: int, max_depth: int) -> list[DelegationChain]:
        self._maybe_fail()
        visible = [d for d in self.delegations.values() if d.created_at <= as_of]
        chains: list[DelegationChain] = []

        def extend(path: list[Delegation]) -> None:
            chains.append(DelegationChain(path[0].from_agent, tuple(path)))
            if len(path) >= max_depth:
                return
            seen = {path[0].from_agent, *(d.to_agent for d in path)}
            for upstream in visible:
                if upstream.to_agent == path[0].from_agent and upstream.from_agent not in seen:
                    extend([upstream, *path])

        for delegation in visible:
            if delegation.to_agent == agent_id:
                extend([delegation])
        return chains

    def supersessions(self, instruction_ids: Sequence[str], as_of: int) -> list[Supersession]:
        self._maybe_fail()
        return [
            Supersession(old, new, at, self.rules[new].instruction.quarantined)
            for new, old, at in self.supersession_log
            if old in instruction_ids and at <= as_of
        ]

    def _node(self, node_id: str) -> LineageNode:
        if node_id in self.utterances:
            utterance = self.utterances[node_id]
            return LineageNode(node_id, "Utterance", utterance.trust, self.speakers.get(node_id))
        if node_id in self.summaries:
            return LineageNode(node_id, "Summary")
        return LineageNode(node_id, "Instruction")

    def lineage_sources(self, node_id: str) -> list[LineageNode]:
        self._maybe_fail()
        if node_id in self.rules:
            return [self._node(src) for src in self.rules[node_id].expressed_by]
        if node_id in self.derived_from:
            return [self._node(src) for src in self.derived_from[node_id]]
        return []

    # --- DecisionRecorder ---------------------------------------------------------

    def record_decision(
        self,
        action: Action,
        decision: Decision,
        used: Sequence[UsedInstruction],
        agent_id: str,
    ) -> None:
        if self.fail_record is not None:
            raise self.fail_record
        self.recorded.append((action, decision, list(used), agent_id))
