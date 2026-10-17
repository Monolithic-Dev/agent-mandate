"""Domain entities (docs/data-model.md sections 2 to 4 and 10).

All models are immutable and reject unknown fields. State changes produce new instances
via ``model_copy(update=...)`` in the store layer. This module has no I/O.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, ConfigDict, Field, model_validator

from mandate.ids import is_valid_id
from mandate.models.nul_free import NulFreeModel
from mandate.models.registry import is_registry_action, is_valid_scope_action_type
from mandate.models.resources import normalise_resource, validate_resource_pattern

# --- enums ---------------------------------------------------------------------------


class Role(StrEnum):
    OWNER = "owner"
    EXTERNAL = "external"


class Channel(StrEnum):
    OWNER_DIRECT = "owner_direct"
    UNTRUSTED_CONTENT = "untrusted_content"


class Trust(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class LineageTrust(StrEnum):
    TRUSTED = "trusted"
    MIXED = "mixed"
    UNTRUSTED = "untrusted"


class Effect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class InstructionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class ActivationKind(StrEnum):
    """How an instruction became active: the owner confirmed it, or it was low-impact
    and came from a trusted owner utterance, so it activated when recorded."""

    CONFIRMED = "confirmed"
    AUTO = "auto"


class AgentKind(StrEnum):
    PRIMARY = "primary"
    SUB = "sub"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING = "pending"
    EXECUTED = "executed"
    DENIED = "denied"


class Result(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class Reason(StrEnum):
    AUTHORIZED = "authorized"
    CONFIRM_RULE = "confirm_rule"
    MIXED_LINEAGE = "mixed_lineage"
    EXPLICIT_DENY = "explicit_deny"
    AUTHORITY_REVOKED = "authority_revoked"
    CONSTRAINT_NOT_MET = "constraint_not_met"
    NO_AUTHORITY_PATH = "no_authority_path"
    CHECK_ERROR = "check_error"


# Which reasons are valid for which result (AUTH-018).
REASONS_FOR_RESULT: dict[Result, frozenset[Reason]] = {
    Result.ALLOW: frozenset({Reason.AUTHORIZED}),
    Result.CONFIRM: frozenset({Reason.CONFIRM_RULE, Reason.MIXED_LINEAGE}),
    Result.DENY: frozenset(
        {
            Reason.EXPLICIT_DENY,
            Reason.AUTHORITY_REVOKED,
            Reason.CONSTRAINT_NOT_MET,
            Reason.NO_AUTHORITY_PATH,
            Reason.CHECK_ERROR,
        }
    ),
}

# --- shared types --------------------------------------------------------------------


def _id_check(prefix: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        if not is_valid_id(value, prefix):
            raise ValueError(f"expected an id with prefix '{prefix}_'")
        return value

    return check


PrincipalId = Annotated[str, AfterValidator(_id_check("prn"))]
UtteranceId = Annotated[str, AfterValidator(_id_check("utt"))]
InstructionId = Annotated[str, AfterValidator(_id_check("ins"))]
ScopeId = Annotated[str, AfterValidator(_id_check("scp"))]
AgentId = Annotated[str, AfterValidator(_id_check("agt"))]
SummaryId = Annotated[str, AfterValidator(_id_check("sum"))]
ActionId = Annotated[str, AfterValidator(_id_check("act"))]
DecisionId = Annotated[str, AfterValidator(_id_check("dec"))]
ApprovalId = Annotated[str, AfterValidator(_id_check("apr"))]
DelegationId = Annotated[str, AfterValidator(_id_check("dlg"))]
TokenId = Annotated[str, AfterValidator(_id_check("tok"))]

EpochMs = Annotated[int, Field(ge=0)]
Name = Annotated[str, Field(min_length=1, max_length=80)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class DomainModel(NulFreeModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Constraints(DomainModel):
    """Optional limits on a scope. Only ``max_amount`` is supported."""

    max_amount: Annotated[int, Field(ge=0)] | None = None

    def to_json(self) -> str:
        return json.dumps(self.model_dump(exclude_none=True), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> Constraints:
        data = json.loads(text or "{}")
        if not isinstance(data, dict):
            raise ValueError("constraints must be a JSON object")
        return cls.model_validate(data)


def _scope_fields_valid(action_type: str, resource_pattern: str) -> tuple[str, str]:
    if not is_valid_scope_action_type(action_type):
        raise ValueError(f"unsupported action type: {action_type!r}")
    return action_type, validate_resource_pattern(resource_pattern)


# --- entities ------------------------------------------------------------------------


class Principal(DomainModel):
    id: PrincipalId
    name: Name
    role: Role


class Utterance(DomainModel):
    id: UtteranceId
    text: Text
    channel: Channel
    trust: Trust
    source_ref: str | None = Field(default=None, max_length=200)
    at: EpochMs

    @model_validator(mode="after")
    def _trust_matches_channel(self) -> Utterance:
        if self.trust is Trust.TRUSTED and self.channel is not Channel.OWNER_DIRECT:
            raise ValueError("only an owner_direct utterance can be trusted")
        return self


class Scope(DomainModel):
    id: ScopeId
    action_type: str
    resource_pattern: str = "*"
    constraints: Constraints = Field(default_factory=Constraints)

    @model_validator(mode="after")
    def _valid(self) -> Scope:
        _scope_fields_valid(self.action_type, self.resource_pattern)
        return self


class Instruction(DomainModel):
    id: InstructionId
    effect: Effect
    text_span: Text
    status: InstructionStatus = InstructionStatus.PENDING
    created_at: EpochMs
    activated_at: EpochMs | None = None
    valid_from: EpochMs | None = None
    valid_to: EpochMs | None = None
    revoked_at: EpochMs | None = None
    quarantined: bool = False
    lineage_trust: LineageTrust
    # Audit: who changed the instruction's state, and how. Null on records made before
    # these fields existed, and for quarantines on a replay clone.
    activated_by: PrincipalId | None = None
    activated_via: ActivationKind | None = None
    revoked_by: PrincipalId | None = None
    # The last quarantine or release: when and by whom.
    quarantine_changed_at: EpochMs | None = None
    quarantine_changed_by: PrincipalId | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Instruction:
        if self.status is InstructionStatus.ACTIVE and self.activated_at is None:
            raise ValueError("an active instruction needs activated_at")
        if self.status is InstructionStatus.REVOKED and self.revoked_at is None:
            raise ValueError("a revoked instruction needs revoked_at")
        if self.activated_at is not None and self.activated_at < self.created_at:
            raise ValueError("activated_at must not precede created_at")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to <= self.valid_from
        ):
            raise ValueError("valid_to must be greater than valid_from")
        return self


class Agent(DomainModel):
    id: AgentId
    name: Name
    kind: AgentKind


class Summary(DomainModel):
    id: SummaryId
    text: Text
    at: EpochMs


class Action(DomainModel):
    id: ActionId
    action_type: str
    resource: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PROPOSED
    at: EpochMs

    @model_validator(mode="after")
    def _valid(self) -> Action:
        if not is_registry_action(self.action_type):
            raise ValueError(f"unknown action type: {self.action_type!r}")
        normalise_resource(self.resource)
        return self


class Delegation(DomainModel):
    id: DelegationId
    from_agent: AgentId
    to_agent: AgentId
    action_type: str
    resource_pattern: str = "*"
    constraints: Constraints = Field(default_factory=Constraints)
    created_at: EpochMs
    valid_from: EpochMs
    valid_to: EpochMs | None = None
    revoked_at: EpochMs | None = None
    via_instruction: InstructionId | None = None

    @model_validator(mode="after")
    def _valid(self) -> Delegation:
        _scope_fields_valid(self.action_type, self.resource_pattern)
        if self.from_agent == self.to_agent:
            raise ValueError("an agent cannot delegate to itself")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be greater than valid_from")
        return self


class Approval(DomainModel):
    id: ApprovalId
    approved: bool
    by: PrincipalId
    at: EpochMs


class TokenRevocation(DomainModel):
    """One agent token the owner has revoked before its expiry.

    ``agent_id`` and ``expires_at`` are known when the token itself was presented, and
    ``None`` when it was revoked by id alone.
    """

    token_id: TokenId
    agent_id: AgentId | None = None
    expires_at: EpochMs | None = None
    revoked_at: EpochMs
    by: PrincipalId


# --- decision ------------------------------------------------------------------------

HopType = Literal[
    "Principal", "Utterance", "Summary", "Instruction", "Delegation", "Agent", "Scope", "Note"
]


class PathHop(DomainModel):
    type: HopType
    id: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=300)


class IgnoredInstruction(DomainModel):
    id: InstructionId
    why: str = Field(min_length=1, max_length=80)


class CheckRequest(DomainModel):
    """A request to authorise one action by one agent."""

    agent_id: AgentId
    action_type: str
    resource: str
    args: dict[str, Any] = Field(default_factory=dict)
    as_of: EpochMs | None = None

    @model_validator(mode="after")
    def _valid(self) -> CheckRequest:
        if not is_registry_action(self.action_type):
            raise ValueError(f"unknown action type: {self.action_type!r}")
        normalise_resource(self.resource)
        return self


class Decision(DomainModel):
    id: DecisionId
    result: Result
    reason: Reason
    as_of: EpochMs
    at: EpochMs
    path: Annotated[list[PathHop], Field(min_length=1)]
    ignored: list[IgnoredInstruction] = Field(default_factory=list)
    latency_ms: Annotated[float, Field(ge=0)] = 0.0
    request_id: str | None = None

    @model_validator(mode="after")
    def _reason_matches_result(self) -> Decision:
        if self.reason not in REASONS_FOR_RESULT[self.result]:
            raise ValueError(f"reason {self.reason.value!r} is not valid for {self.result.value!r}")
        return self

    def path_json(self) -> str:
        return json.dumps([hop.model_dump() for hop in self.path], separators=(",", ":"))

    def ignored_json(self) -> str:
        return json.dumps([item.model_dump() for item in self.ignored], separators=(",", ":"))
