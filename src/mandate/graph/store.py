"""The FalkorDB adapter for the authority ports (reader and recorder) plus the writes that
keep the graph consistent. One instance serves one tenant graph.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from mandate.authority.delegation import MAX_CHAIN_DEPTH
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
from mandate.errors import (
    AlreadyActive,
    Conflict,
    NotFound,
    UntrustedLineage,
    ValidationFailure,
)
from mandate.graph.client import GraphClient, Row
from mandate.graph.mapping import (
    action_from_props,
    decision_from_props,
    delegation_from_props,
    instruction_from_props,
    scope_from_props,
)
from mandate.graph.tenants import REPLAY_MARKER
from mandate.ids import new_id
from mandate.models.domain import (
    Action,
    ActionStatus,
    ActivationKind,
    Agent,
    Approval,
    Constraints,
    Decision,
    Delegation,
    Effect,
    Instruction,
    InstructionStatus,
    LineageTrust,
    Principal,
    Scope,
    Summary,
    TokenRevocation,
    Trust,
    Utterance,
)

# Read at most this many nodes before ranking them for display.
GRAPH_FETCH_CAP = 5000


def _revocation_from_props(props: dict[str, Any]) -> TokenRevocation:
    return TokenRevocation(
        token_id=props["id"],
        agent_id=props.get("agent_id"),
        expires_at=props.get("expires_at"),
        revoked_at=props["revoked_at"],
        by=props["by"],
    )


def _label_for(node_id: str) -> str:
    prefix = node_id.split("_", 1)[0]
    return {"utt": "Utterance", "sum": "Summary", "ins": "Instruction"}.get(prefix, "")


class FalkorAuthorityStore:
    """Implements ``AuthorityReader`` and ``DecisionRecorder`` against one tenant graph."""

    def __init__(self, client: GraphClient, graph_name: str) -> None:
        self._client = client
        self.graph_name = graph_name

    def _run(self, query: str, params: dict[str, Any] | None = None) -> list[Row]:
        return self._client.run(self.graph_name, query, params)

    # --- AuthorityReader ----------------------------------------------------------

    def instructions_for_agent(self, agent_id: str, as_of: int) -> list[InstructionRecord]:
        rows = self._run("q01_direct_candidates", {"agent_id": agent_id, "as_of": as_of})
        return [
            InstructionRecord(instruction_from_props(r["i"]), scope_from_props(r["s"]), agent_id)
            for r in rows
        ]

    def delegation_chains(self, agent_id: str, as_of: int, max_depth: int) -> list[DelegationChain]:
        if max_depth > MAX_CHAIN_DEPTH:
            raise ValueError(f"the delegation query supports a depth of at most {MAX_CHAIN_DEPTH}")
        rows = self._run("q02_delegation_chains", {"agent_id": agent_id, "as_of": as_of})
        chains: list[DelegationChain] = []
        for row in rows:
            agents: list[str] = row["agents"]
            hops = tuple(
                delegation_from_props(props, agents[index], agents[index + 1])
                for index, props in enumerate(row["hops"])
            )
            if 0 < len(hops) <= max_depth:
                chains.append(DelegationChain(agents[0], hops))
        return chains

    def supersessions(self, instruction_ids: Sequence[str], as_of: int) -> list[Supersession]:
        if not instruction_ids:
            return []
        rows = self._run(
            "q03_supersessions", {"instruction_ids": list(instruction_ids), "as_of": as_of}
        )
        return [
            Supersession(r["superseded_id"], r["by_id"], r["at"], bool(r["by_quarantined"]))
            for r in rows
        ]

    def lineage_sources(self, node_id: str) -> list[LineageNode]:
        label = _label_for(node_id)
        if label == "Instruction":
            rows = self._run("q04_lineage_instruction", {"node_id": node_id})
        elif label == "Summary":
            rows = self._run("q04_lineage_summary", {"node_id": node_id})
        else:
            return []
        return [
            LineageNode(
                r["id"],
                r["label"],
                Trust(r["trust"]) if r.get("trust") else None,
                r.get("principal_id"),
            )
            for r in rows
            if r["id"] is not None
        ]

    # --- DecisionRecorder ---------------------------------------------------------

    def record_decision(
        self,
        action: Action,
        decision: Decision,
        used: Sequence[UsedInstruction],
        agent_id: str,
    ) -> None:
        # A sentinel row keeps the query returning a row when ``used`` is empty.
        used_rows: list[dict[str, str | None]] = [
            {"instruction_id": u.instruction_id, "role": u.role} for u in used
        ]
        used_rows.append({"instruction_id": None, "role": None})
        rows = self._run(
            "w12_record_decision",
            {
                "agent_id": agent_id,
                "action_id": action.id,
                "action_type": action.action_type,
                "resource": action.resource,
                "args": json.dumps(action.args, sort_keys=True),
                "action_status": action.status.value,
                "action_at": action.at,
                "decision_id": decision.id,
                "result": decision.result.value,
                "reason": decision.reason.value,
                "as_of": decision.as_of,
                "decision_at": decision.at,
                "path_json": decision.path_json(),
                "ignored_json": decision.ignored_json(),
                "latency_ms": decision.latency_ms,
                "request_id": decision.request_id,
                "used": used_rows,
            },
        )
        if not rows or rows[0]["recorded"] != 1:
            raise NotFound(f"agent {agent_id!r} does not exist in this tenant")

    def get_decision(self, decision_id: str) -> RecordedDecision:
        rows = self._run("q10_decision_path", {"decision_id": decision_id})
        if not rows:
            raise NotFound("no such decision")
        row = rows[0]
        used = [
            UsedInstruction(item["id"], item["role"])
            for item in row["used"]
            if item["id"] is not None
        ]
        return RecordedDecision(
            decision_from_props(row["dec"]),
            action_from_props(row["a"]),
            used,
            row["agent_id"] or "",
        )

    # --- writes: entities ---------------------------------------------------------

    def create_principal(self, principal: Principal) -> Principal:
        self._run(
            "w01_create_principal",
            {"id": principal.id, "name": principal.name, "role": principal.role.value},
        )
        return principal

    def create_agent(self, agent: Agent) -> Agent:
        self._run(
            "w02_create_agent", {"id": agent.id, "name": agent.name, "kind": agent.kind.value}
        )
        return agent

    def create_utterance(self, utterance: Utterance, speaker_id: str) -> Utterance:
        rows = self._run(
            "w03_create_utterance",
            {
                "speaker_id": speaker_id,
                "id": utterance.id,
                "text": utterance.text,
                "channel": utterance.channel.value,
                "trust": utterance.trust.value,
                "at": utterance.at,
                "source_ref": utterance.source_ref,
            },
        )
        if not rows:
            raise NotFound("no such principal")
        return utterance

    def create_summary(self, summary: Summary, derived_from: Sequence[str]) -> Summary:
        self._run("w04_create_summary", {"id": summary.id, "text": summary.text, "at": summary.at})
        for source_id in derived_from:
            query = {
                "Utterance": "w04_derive_from_utterance",
                "Summary": "w04_derive_from_summary",
                "Instruction": "w04_derive_from_instruction",
            }.get(_label_for(source_id))
            if query is None:
                raise ValidationFailure(f"cannot derive a summary from {source_id!r}")
            rows = self._run(query, {"summary_id": summary.id, "source_id": source_id})
            if not rows or rows[0]["linked"] != 1:
                raise NotFound(f"no such source: {source_id!r}")
        return summary

    # --- writes: instructions -----------------------------------------------------

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
        """Create a pending instruction expressed by an utterance or summary."""
        if not agent_ids:
            raise ValidationFailure("an instruction must apply to at least one agent")
        label = _label_for(source_id)
        if label not in {"Utterance", "Summary"}:
            raise ValidationFailure("an instruction must be expressed by an utterance or summary")
        scope = Scope(
            id=new_id("scp"),
            action_type=action_type,
            resource_pattern=resource_pattern,
            constraints=Constraints(max_amount=max_amount),
        )
        known = {r["id"] for r in self._run("q05_agents_exist", {"ids": list(agent_ids)})}
        missing = set(agent_ids) - known
        if missing:
            raise NotFound(f"unknown agents: {sorted(missing)}")
        new_instruction_id = instruction_id or new_id("ins", now_ms=created_at)
        query = (
            "w05_create_instruction_from_utterance"
            if label == "Utterance"
            else "w05_create_instruction_from_summary"
        )
        rows = self._run(
            query,
            {
                "source_id": source_id,
                "id": new_instruction_id,
                "effect": effect.value,
                "text_span": text_span,
                "created_at": created_at,
                "scope_id": scope.id,
                "action_type": scope.action_type,
                "resource_pattern": scope.resource_pattern,
                "constraints": scope.constraints.to_json(),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "agent_ids": list(agent_ids),
            },
        )
        if not rows or rows[0]["applied"] != len(agent_ids):
            raise NotFound("source not found, or instruction could not be linked to its agents")
        trust = compute_lineage(self, new_instruction_id).trust
        self._run("w13_set_lineage_trust", {"id": new_instruction_id, "lineage_trust": trust.value})
        return Instruction(
            id=new_instruction_id,
            effect=effect,
            text_span=text_span,
            status=InstructionStatus.PENDING,
            created_at=created_at,
            valid_from=valid_from,
            valid_to=valid_to,
            lineage_trust=trust,
        )

    def get_instruction(self, instruction_id: str) -> Instruction:
        rows = self._run("q06_instruction_by_id", {"id": instruction_id})
        if not rows:
            raise NotFound("no such instruction")
        return instruction_from_props(rows[0]["i"])

    def activate_instruction(
        self,
        instruction_id: str,
        at: int,
        *,
        by: str | None = None,
        via: ActivationKind | None = None,
    ) -> Instruction:
        """Activate a pending instruction. Untrusted lineage is refused (AUTH-006)."""
        current = self.get_instruction(instruction_id)
        trust = compute_lineage(self, instruction_id).trust
        if trust is LineageTrust.UNTRUSTED:
            raise UntrustedLineage("this instruction has no trusted origin and cannot be activated")
        rows = self._run(
            "w06_activate_instruction",
            {
                "id": instruction_id,
                "at": at,
                "lineage_trust": trust.value,
                "by": by,
                "via": via.value if via is not None else None,
            },
        )
        if not rows or rows[0]["changed"] == 0:
            raise AlreadyActive(f"instruction is {current.status.value}, not pending")
        return self.get_instruction(instruction_id)

    def revoke_instruction(
        self, instruction_id: str, at: int, *, by: str | None = None
    ) -> Instruction:
        self.get_instruction(instruction_id)
        rows = self._run("w07_revoke_instruction", {"id": instruction_id, "at": at, "by": by})
        if not rows or rows[0]["changed"] == 0:
            raise Conflict("instruction is already revoked")
        return self.get_instruction(instruction_id)

    def set_quarantined(
        self,
        instruction_ids: Sequence[str],
        value: bool,
        *,
        at: int | None = None,
        by: str | None = None,
    ) -> int:
        if not instruction_ids:
            return 0
        rows = self._run(
            "w08_set_quarantined",
            {"ids": list(instruction_ids), "value": value, "at": at, "by": by},
        )
        return int(rows[0]["changed"]) if rows else 0

    def supersede(self, new_instruction_id: str, old_instruction_id: str, at: int) -> None:
        rows = self._run(
            "w09_supersede",
            {"new_id": new_instruction_id, "old_id": old_instruction_id, "at": at},
        )
        if not rows or rows[0]["changed"] == 0:
            raise NotFound("both instructions must exist to record a supersession")

    # --- writes: delegations ------------------------------------------------------

    def create_delegation(self, delegation: Delegation) -> Delegation:
        rows = self._run(
            "w10_create_delegation",
            {
                "id": delegation.id,
                "from_agent": delegation.from_agent,
                "to_agent": delegation.to_agent,
                "action_type": delegation.action_type,
                "resource_pattern": delegation.resource_pattern,
                "constraints": delegation.constraints.to_json(),
                "created_at": delegation.created_at,
                "valid_from": delegation.valid_from,
                "valid_to": delegation.valid_to,
                "via_instruction": delegation.via_instruction,
            },
        )
        if not rows or rows[0]["created"] != 1:
            raise NotFound("both agents must exist to create a delegation")
        return delegation

    def revoke_delegation(self, delegation_id: str, at: int) -> None:
        rows = self._run("w11_revoke_delegation", {"id": delegation_id, "at": at})
        if not rows or rows[0]["changed"] == 0:
            raise Conflict("delegation is unknown or already revoked")

    # --- AuthorityLookup ----------------------------------------------------------

    def get_principal(self, principal_id: str) -> Principal:
        rows = self._run("q07_principal_by_id", {"id": principal_id})
        if not rows:
            raise NotFound("no such principal")
        return Principal.model_validate(rows[0]["p"])

    def get_agent(self, agent_id: str) -> Agent:
        rows = self._run("q08_agent_by_id", {"id": agent_id})
        if not rows:
            raise NotFound("no such agent")
        return Agent.model_validate(rows[0]["a"])

    def list_agents(self) -> list[Agent]:
        return [Agent.model_validate(r["a"]) for r in self._run("q08_agents_list")]

    # --- LineageReader ------------------------------------------------------------

    def derivation_step(self, instruction_ids: Sequence[str]) -> tuple[list[str], list[str]]:
        if not instruction_ids:
            return [], []
        rows = self._run("q05_blast_radius_step", {"instruction_ids": list(instruction_ids)})
        if not rows:
            return [], []
        summaries = [s for s in rows[0]["summaries"] if s is not None]
        derived = [d for d in rows[0]["derived_instruction_ids"] if d is not None]
        return summaries, derived

    def decisions_using(self, instruction_ids: Sequence[str]) -> list[DecisionSummary]:
        if not instruction_ids:
            return []
        rows = self._run("q06_decisions_using", {"instruction_ids": list(instruction_ids)})
        return [
            DecisionSummary(decision_from_props(r["dec"]), action_from_props(r["a"]), r["agent_id"])
            for r in rows
        ]

    def reliance_counts(self, limit: int = 20) -> list[RelianceCount]:
        rows = self._run("q18_reliance_by_instruction", {"limit": max(1, limit)})
        return [
            RelianceCount(
                r["instruction_id"],
                r["decisions"],
                r["as_winner"],
                r["agents"],
                r["first_at"],
                r["last_at"],
            )
            for r in rows
        ]

    def graph_snapshot(self, limit: int = 500) -> GraphSnapshot:
        rows = self._run("q19_graph_nodes", {"limit": GRAPH_FETCH_CAP})
        nodes = [
            GraphNode(str(r["props"]["id"]), str(r["label"]), dict(r["props"]))
            for r in rows
            if r["props"].get("id")
        ]
        kept, truncated = keep_nodes(nodes, limit)
        ids = [n.id for n in kept]
        edges = (
            [
                GraphEdge(r["source"], r["target"], r["type"], dict(r["props"] or {}))
                for r in self._run("q20_graph_edges", {"ids": ids})
            ]
            if ids
            else []
        )
        return GraphSnapshot(kept, edges, truncated or len(rows) >= GRAPH_FETCH_CAP)

    def delegations_via(self, instruction_ids: Sequence[str]) -> list[str]:
        if not instruction_ids:
            return []
        rows = self._run("q07_delegations_via", {"instruction_ids": list(instruction_ids)})
        return [r["id"] for r in rows]

    @contextmanager
    def clone_for_replay(self) -> Iterator[FalkorAuthorityStore]:
        """Copy this tenant's graph with GRAPH.COPY and remove the copy on exit, always."""
        clone_name = f"{self.graph_name}{REPLAY_MARKER}{new_id('act')[4:].lower()}"
        self._client.copy_graph(self.graph_name, clone_name)
        try:
            yield FalkorAuthorityStore(self._client, clone_name)
        finally:
            self._client.delete_graph(clone_name)

    # --- listings -----------------------------------------------------------------

    def list_principals(self) -> list[Principal]:
        return [Principal.model_validate(r["p"]) for r in self._run("q17_principals_list")]

    def list_instructions(
        self, *, status: str | None = None, agent_id: str | None = None
    ) -> list[InstructionRecord]:
        rows = self._run("q14_instructions_list", {"status": status, "agent_id": agent_id})
        return [
            InstructionRecord(
                instruction_from_props(r["i"]), scope_from_props(r["s"]), r["agent_id"]
            )
            for r in rows
        ]

    def list_decisions(
        self, *, agent_id: str | None = None, limit: int = 50
    ) -> list[DecisionSummary]:
        rows = self._run("q15_decisions_list", {"agent_id": agent_id, "limit": limit})
        return [
            DecisionSummary(decision_from_props(r["d"]), action_from_props(r["a"]), r["agent_id"])
            for r in rows
        ]

    def decision_activity(self, since: int, limit: int) -> list[ActivityRow]:
        rows = self._run("q33_decision_activity", {"since": since, "limit": limit})
        return [
            ActivityRow(
                at=r["at"],
                result=r["result"],
                reason=r["reason"],
                action_type=r["action_type"],
                agent_id=r["agent_id"],
                latency_ms=float(r["latency_ms"] or 0.0),
            )
            for r in rows
        ]

    def list_actions(
        self, *, status: ActionStatus | None = None, limit: int = 50
    ) -> list[StoredAction]:
        rows = self._run(
            "q16_actions_list", {"status": status.value if status else None, "limit": limit}
        )
        return [
            StoredAction(action_from_props(r["a"]), r["agent_id"], r["decision_id"]) for r in rows
        ]

    # --- actions and approvals ----------------------------------------------------

    def get_action(self, action_id: str) -> StoredAction:
        rows = self._run("q13_action_by_id", {"id": action_id})
        if not rows:
            raise NotFound("no such action")
        row = rows[0]
        return StoredAction(action_from_props(row["a"]), row["agent_id"], row["decision_id"])

    def set_action_status(self, action_id: str, status: ActionStatus) -> None:
        rows = self._run("w16_set_action_status", {"id": action_id, "status": status.value})
        if not rows or rows[0]["changed"] == 0:
            raise NotFound("no such action")

    def resolve_pending_action(
        self, action_id: str, approval: Approval, new_status: ActionStatus
    ) -> bool:
        rows = self._run(
            "w17_resolve_pending_action",
            {
                "action_id": action_id,
                "new_status": new_status.value,
                "approval_id": approval.id,
                "approved": approval.approved,
                "by": approval.by,
                "at": approval.at,
            },
        )
        return bool(rows) and rows[0]["changed"] == 1

    # --- agent tokens -------------------------------------------------------------

    def revoke_token(self, revocation: TokenRevocation) -> TokenRevocation:
        rows = self._run(
            "w18_revoke_token",
            {
                "token_id": revocation.token_id,
                "agent_id": revocation.agent_id,
                "expires_at": revocation.expires_at,
                "revoked_at": revocation.revoked_at,
                "by": revocation.by,
            },
        )
        return _revocation_from_props(rows[0]["r"])

    def token_revoked(self, token_id: str) -> bool:
        rows = self._run("q21_token_revoked", {"token_id": token_id})
        return bool(rows) and int(rows[0]["revoked"]) > 0

    def list_token_revocations(self, limit: int = 100) -> list[TokenRevocation]:
        rows = self._run("q22_token_revocations_list", {"limit": limit})
        return [_revocation_from_props(r["r"]) for r in rows]

    # --- change marker ------------------------------------------------------------

    def change_marker(self) -> ChangeMarker:
        row = self._run("q23_change_marker", {"pending": ActionStatus.PENDING.value})[0]
        last = row["last_decision_at"]
        return ChangeMarker(
            decisions=int(row["decisions"]),
            last_decision_at=None if last is None else int(last),
            pending=tuple(sorted(str(p) for p in row["pending"] if p)),
            rules=rules_digest(row["rules"]),
        )

    # --- diagnostics --------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        return {r["label"]: int(r["n"]) for r in self._run("q09_tenant_counts") if r["label"]}
