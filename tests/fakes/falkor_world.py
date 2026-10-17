"""The same builder API as ``InMemoryStore``, backed by a real FalkorDB tenant graph.

It lets contract and differential tests run one scenario against both backends. It
composes the production store's write methods, so those get exercised too.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mandate.authority.ports import (
    DelegationChain,
    InstructionRecord,
    LineageNode,
    Supersession,
    UsedInstruction,
)
from mandate.clock import FixedClock
from mandate.errors import Conflict
from mandate.graph.client import GraphClient
from mandate.graph.store import FalkorAuthorityStore
from mandate.ids import new_id
from mandate.models.domain import (
    Action,
    Agent,
    AgentKind,
    Channel,
    Constraints,
    Decision,
    Delegation,
    Effect,
    Instruction,
    LineageTrust,
    Principal,
    Role,
    Summary,
    Utterance,
)
from mandate.models.trust import compute_trust


class FalkorBuilder:
    def __init__(self, client: GraphClient, graph_name: str, clock: FixedClock | None = None):
        self.client = client
        self.graph_name = graph_name
        self.store = FalkorAuthorityStore(client, graph_name)
        self.clock = clock or FixedClock()

    def _at(self, at: int | None) -> int:
        return self.clock.now_ms() if at is None else at

    # --- builders (same signatures as InMemoryStore) -------------------------------

    def add_principal(self, name: str, role: Role) -> Principal:
        return self.store.create_principal(Principal(id=new_id("prn"), name=name, role=role))

    def add_agent(self, name: str, kind: AgentKind = AgentKind.PRIMARY) -> Agent:
        return self.store.create_agent(Agent(id=new_id("agt"), name=name, kind=kind))

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
        return self.store.create_utterance(utterance, principal.id)

    def summarise(self, *sources: str, text: str = "summary", at: int | None = None) -> Summary:
        summary = Summary(id=new_id("sum"), text=text, at=self._at(at))
        return self.store.create_summary(summary, list(sources))

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
        created = self._at(at)
        instruction = self.store.create_instruction(
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
            return self.store.activate_instruction(instruction.id, created)
        if activate and untrusted and force_active:
            # Simulate tampered data: the store itself refuses this activation (AUTH-006).
            self.client.run_admin_text(
                self.graph_name,
                "MATCH (i:Instruction {id: $id}) SET i.status = 'active', "
                "i.activated_at = $at, i.valid_from = coalesce(i.valid_from, $at)",
                {"id": instruction.id, "at": created},
            )
            return self.store.get_instruction(instruction.id)
        return instruction

    def revoke(self, instruction: Instruction, at: int | None = None) -> Instruction:
        try:
            return self.store.revoke_instruction(instruction.id, self._at(at))
        except Conflict:
            return self.store.get_instruction(instruction.id)

    def quarantine(self, instruction: Instruction, value: bool = True) -> Instruction:
        self.store.set_quarantined([instruction.id], value)
        return self.store.get_instruction(instruction.id)

    def supersede(self, new: Instruction, old: Instruction, at: int | None = None) -> None:
        self.store.supersede(new.id, old.id, self._at(at))

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
        delegation = Delegation(
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
        return self.store.create_delegation(delegation)

    def revoke_delegation(self, delegation: Delegation | str, at: int | None = None) -> Any:
        """Id form (the port) raises on a repeat; the object form keeps the first revocation."""
        revoked_at = self._at(at)
        if isinstance(delegation, str):
            self.store.revoke_delegation(delegation, revoked_at)
            return None
        try:
            self.store.revoke_delegation(delegation.id, revoked_at)
        except Conflict:
            return delegation
        return delegation.model_copy(update={"revoked_at": revoked_at})

    def __getattr__(self, name: str) -> Any:
        """Expose the production store's own methods (writes and lookups) unchanged."""
        return getattr(self.store, name)

    # --- ports (delegating) ---------------------------------------------------------

    def instructions_for_agent(self, agent_id: str, as_of: int) -> list[InstructionRecord]:
        return self.store.instructions_for_agent(agent_id, as_of)

    def delegation_chains(self, agent_id: str, as_of: int, max_depth: int) -> list[DelegationChain]:
        return self.store.delegation_chains(agent_id, as_of, max_depth)

    def supersessions(self, instruction_ids: Sequence[str], as_of: int) -> list[Supersession]:
        return self.store.supersessions(instruction_ids, as_of)

    def lineage_sources(self, node_id: str) -> list[LineageNode]:
        return self.store.lineage_sources(node_id)

    def record_decision(
        self,
        action: Action,
        decision: Decision,
        used: Sequence[UsedInstruction],
        agent_id: str,
    ) -> None:
        self.store.record_decision(action, decision, used, agent_id)


def attrs(obj: Any) -> dict[str, Any]:  # small helper for debugging in tests
    return dict(vars(obj))
