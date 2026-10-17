"""Ports: what the authority core needs from the outside world.

The core depends only on these protocols. ``mandate.graph`` implements them against
FalkorDB; tests implement them in memory. Nothing here imports an I/O library.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from mandate.models.domain import (
    Action,
    ActionStatus,
    ActivationKind,
    Agent,
    Approval,
    Decision,
    Delegation,
    Effect,
    Instruction,
    Principal,
    Scope,
    Summary,
    TokenRevocation,
    Trust,
    Utterance,
)

# --- records returned by the reader ---------------------------------------------------


@dataclass(frozen=True)
class InstructionRecord:
    """An instruction with its scope and the agent it applies to."""

    instruction: Instruction
    scope: Scope
    agent_id: str


@dataclass(frozen=True)
class DelegationChain:
    """A path of delegations ending at the agent being checked, ordered root to target."""

    root_agent_id: str
    hops: tuple[Delegation, ...]


@dataclass(frozen=True)
class Supersession:
    """A recorded fact that ``by_id`` replaced ``superseded_id`` at time ``at``."""

    superseded_id: str
    by_id: str
    at: int
    by_quarantined: bool


@dataclass(frozen=True)
class LineageNode:
    """A node in the derivation chain of an instruction."""

    id: str
    label: Literal["Utterance", "Summary", "Instruction"]
    trust: Trust | None = None  # set for utterances
    principal_id: str | None = None  # speaker, set for utterances


@dataclass(frozen=True)
class UsedInstruction:
    instruction_id: str
    role: Literal["winner", "considered"]


@dataclass(frozen=True)
class StoredAction:
    """A stored action, the agent that proposed it and the decision that checked it."""

    action: Action
    agent_id: str
    decision_id: str | None = None


@dataclass(frozen=True)
class RelianceCount:
    """How much the recorded decisions leaned on one instruction."""

    instruction_id: str
    decisions: int  # decisions that used it, as winner or merely considered
    as_winner: int  # decisions it actually decided
    agents: int  # distinct agents those decisions concerned
    first_at: int
    last_at: int


@dataclass(frozen=True)
class ActivityRow:
    """One decision, reduced to what the activity overview counts."""

    at: int
    result: str
    reason: str
    action_type: str
    agent_id: str
    latency_ms: float


@dataclass(frozen=True)
class DecisionSummary:
    """A stored decision with its action and the agent that asked."""

    decision: Decision
    action: Action
    agent_id: str


@dataclass(frozen=True)
class RecordedDecision:
    """A stored decision with its action and the instructions it used."""

    decision: Decision
    action: Action
    used: list[UsedInstruction]
    agent_id: str  # the agent that proposed the action


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    props: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    type: str
    props: dict[str, Any]


@dataclass(frozen=True)
class GraphSnapshot:
    """A bounded picture of a tenant's graph, for display only (never for decisions)."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


# When a graph is cut to a limit, the authority keeps its place and the decision log goes
# first: a truncated picture still shows who said what and which rules exist.
GRAPH_LABEL_ORDER = (
    "Principal",
    "Agent",
    "Utterance",
    "Summary",
    "Instruction",
    "Scope",
    "Approval",
    "Action",
    "Decision",
)


@dataclass(frozen=True)
class ChangeMarker:
    """A cheap summary of what the console shows; when it changes, something happened.

    Read about once a second per open console, from whichever process wrote the change
    (the REST API or an MCP server), so the console can update without polling every list.
    """

    decisions: int
    last_decision_at: int | None
    pending: tuple[str, ...]  # held action ids, sorted
    rules: str  # a digest of every instruction's id, status, quarantine flag and trust


def rules_digest(rows: Iterable[Sequence[object]]) -> str:
    """Order-independent digest of instruction (id, status, quarantined, trust) rows."""
    text = "\n".join(sorted("|".join(str(v) for v in row) for row in rows if row and row[0]))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def keep_nodes(nodes: Sequence[GraphNode], limit: int) -> tuple[list[GraphNode], bool]:
    """The nodes to show, at most ``limit``, ranked by label then id, and whether any were cut."""
    rank = {label: index for index, label in enumerate(GRAPH_LABEL_ORDER)}
    ordered = sorted(nodes, key=lambda n: (rank.get(n.label, len(rank)), n.id))
    return ordered[:limit], len(ordered) > limit


# --- ports ---------------------------------------------------------------------------


class AuthorityReader(Protocol):
    """Read side used by ``check_authority``. All times are epoch milliseconds."""

    def instructions_for_agent(self, agent_id: str, as_of: int) -> Sequence[InstructionRecord]:
        """Instructions that apply to ``agent_id`` and were created at or before ``as_of``.

        Returns every status (pending, active, revoked, quarantined): the engine applies
        the rules, because it needs revoked and untrusted ones to explain a decision.
        """
        ...

    def delegation_chains(
        self, agent_id: str, as_of: int, max_depth: int
    ) -> Sequence[DelegationChain]:
        """All delegation paths of length 1..max_depth ending at ``agent_id``.

        Includes delegations created at or before ``as_of`` whether or not they have since
        been revoked. Paths must not repeat an agent.
        """
        ...

    def supersessions(self, instruction_ids: Sequence[str], as_of: int) -> Sequence[Supersession]:
        """Supersessions of the given instructions recorded at or before ``as_of``."""
        ...

    def lineage_sources(self, node_id: str) -> Sequence[LineageNode]:
        """The nodes ``node_id`` derives from, one step up.

        For an instruction: the utterances or summaries that express it. For a summary: the
        utterances, summaries or instructions it was derived from. For an utterance: none.
        """
        ...


class DecisionRecorder(Protocol):
    """Write side used by ``check_authority`` to keep the audit trail."""

    def record_decision(
        self,
        action: Action,
        decision: Decision,
        used: Sequence[UsedInstruction],
        agent_id: str,
    ) -> None: ...


class AuthorityWriter(Protocol):
    """Write side used by the authority service. Each call is one consistent change."""

    def create_principal(self, principal: Principal) -> Principal: ...

    def create_agent(self, agent: Agent) -> Agent: ...

    def create_utterance(self, utterance: Utterance, speaker_id: str) -> Utterance: ...

    def create_summary(self, summary: Summary, derived_from: Sequence[str]) -> Summary: ...

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
        """Create a pending instruction and compute its lineage trust."""
        ...

    def get_instruction(self, instruction_id: str) -> Instruction: ...

    def activate_instruction(
        self,
        instruction_id: str,
        at: int,
        *,
        by: str | None = None,
        via: ActivationKind | None = None,
    ) -> Instruction:
        """Activate a pending instruction. Must refuse untrusted lineage (AUTH-006).

        ``by`` and ``via`` are recorded for audit: who activated it, and how.
        """
        ...

    def revoke_instruction(
        self, instruction_id: str, at: int, *, by: str | None = None
    ) -> Instruction:
        """Revoke an instruction. Raises ``Conflict`` if it is already revoked."""
        ...

    def set_quarantined(
        self,
        instruction_ids: Sequence[str],
        value: bool,
        *,
        at: int | None = None,
        by: str | None = None,
    ) -> int:
        """Quarantine or release instructions, recording when and by whom (when given)."""
        ...

    def supersede(self, new_instruction_id: str, old_instruction_id: str, at: int) -> None: ...

    def create_delegation(self, delegation: Delegation) -> Delegation: ...

    def revoke_delegation(self, delegation_id: str, at: int) -> None: ...

    def set_action_status(self, action_id: str, status: ActionStatus) -> None: ...

    def resolve_pending_action(
        self, action_id: str, approval: Approval, new_status: ActionStatus
    ) -> bool:
        """Atomically move a pending action to `new_status` and record the approval.

        Returns False if the action was not pending (for example, already resolved).
        """
        ...

    def revoke_token(self, revocation: TokenRevocation) -> TokenRevocation:
        """Record that an agent token is revoked. Idempotent: revoking a token again keeps
        and returns the first record."""
        ...


class AuthorityLookup(Protocol):
    """Reads used by the service to validate requests and explain decisions."""

    def get_principal(self, principal_id: str) -> Principal: ...

    def get_agent(self, agent_id: str) -> Agent: ...

    def list_agents(self) -> list[Agent]: ...

    def get_decision(self, decision_id: str) -> RecordedDecision: ...

    def get_action(self, action_id: str) -> StoredAction: ...

    def list_principals(self) -> list[Principal]: ...

    def list_instructions(
        self, *, status: str | None = None, agent_id: str | None = None
    ) -> list[InstructionRecord]:
        """Instructions with their scope, one record per agent they apply to."""
        ...

    def list_decisions(
        self, *, agent_id: str | None = None, limit: int = 50
    ) -> list[DecisionSummary]:
        """Newest first."""
        ...

    def list_actions(
        self, *, status: ActionStatus | None = None, limit: int = 50
    ) -> list[StoredAction]:
        """Newest first."""
        ...

    def graph_snapshot(self, limit: int = 500) -> GraphSnapshot:
        """At most ``limit`` nodes (see ``keep_nodes``) and every edge between them."""
        ...

    def token_revoked(self, token_id: str) -> bool: ...

    def change_marker(self) -> ChangeMarker: ...

    def list_token_revocations(self, limit: int = 100) -> list[TokenRevocation]:
        """Newest first."""
        ...

    def decision_activity(self, since: int, limit: int) -> list[ActivityRow]:
        """Decisions made at or after ``since``, newest first, at most ``limit``."""
        ...


class LineageReader(Protocol):
    """Reads used to trace what an instruction affected, and to replay without it."""

    def derivation_step(self, instruction_ids: Sequence[str]) -> tuple[list[str], list[str]]:
        """One step of derivation: (summaries derived from the instructions, instructions
        expressed by those summaries)."""
        ...

    def decisions_using(self, instruction_ids: Sequence[str]) -> list[DecisionSummary]:
        """Decisions that used any of the instructions, oldest first."""
        ...

    def reliance_counts(self, limit: int = 20) -> list[RelianceCount]:
        """Instructions ranked by how many decisions used them, most relied-on first."""
        ...

    def delegations_via(self, instruction_ids: Sequence[str]) -> list[str]:
        """Ids of delegations created on the authority of any of the instructions."""
        ...

    def clone_for_replay(self) -> AbstractContextManager[AuthorityStore]:
        """A temporary, independent copy of this tenant's data, removed on exit."""
        ...


class AuthorityStore(
    AuthorityReader, AuthorityWriter, AuthorityLookup, LineageReader, DecisionRecorder, Protocol
):
    """Everything a tenant's store provides."""
