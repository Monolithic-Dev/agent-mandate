"""Request and response bodies for the REST API (docs/api-spec.md)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from mandate.models.accounts import (
    EMAIL_MAX,
    PASSWORD_MAX,
    PASSWORD_MIN,
    AuditEvent,
    UserRole,
)
from mandate.models.domain import (
    Action,
    AgentId,
    AgentKind,
    Channel,
    Decision,
    DelegationId,
    EpochMs,
    IgnoredInstruction,
    Instruction,
    InstructionId,
    PathHop,
    PrincipalId,
    Reason,
    Result,
    Role,
    Scope,
    TokenId,
)
from mandate.models.nul_free import NulFreeModel
from mandate.models.webhooks import WebhookEvent, WebhookKind


class ApiModel(NulFreeModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- tenants, principals, agents ---------------------------------------------------


class CreateTenant(ApiModel):
    tenant_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)


class TenantOut(ApiModel):
    tenant_id: str
    name: str
    graph: str
    created_at: int
    content_principal_id: str | None = None


class CreatePrincipal(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    role: Role


class CreateAgent(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    kind: AgentKind


# --- utterances and instructions ---------------------------------------------------


class UtteranceIn(ApiModel):
    principal_id: PrincipalId
    text: str = Field(min_length=1, max_length=4000)
    channel: Channel
    source_ref: str | None = Field(default=None, max_length=200)
    at: EpochMs | None = None
    agent_ids: list[AgentId] | None = None


class PreviewIn(ApiModel):
    """What the owner is about to say; previewed as said on the owner's direct channel."""

    principal_id: PrincipalId
    text: str = Field(min_length=1, max_length=4000)
    agent_ids: list[AgentId] | None = None


class IngestedInstructionOut(ApiModel):
    instruction: Instruction
    action_type: str
    resource_pattern: str
    max_amount: int | None
    needs_confirmation: bool
    inert: bool


class UtteranceOut(ApiModel):
    utterance_id: str
    channel: Channel
    trust: str
    at: int
    instructions: list[IngestedInstructionOut]
    unparsed: list[str]


class ByPrincipal(ApiModel):
    by: PrincipalId


class InstructionView(ApiModel):
    instruction: Instruction
    scope: Scope
    agent_id: str


# --- delegations -------------------------------------------------------------------


class DelegationIn(ApiModel):
    from_agent: AgentId
    to_agent: AgentId
    action_type: str
    resource_pattern: str = "*"
    max_amount: int | None = Field(default=None, ge=0)
    valid_to: EpochMs | None = None
    via_instruction: InstructionId | None = None
    by: PrincipalId


class DelegationOut(ApiModel):
    id: DelegationId
    created_at: int


# --- checks, tool calls, approvals -------------------------------------------------


class CheckIn(ApiModel):
    agent_id: AgentId
    action_type: str
    resource: str
    args: dict[str, Any] = Field(default_factory=dict)
    as_of: EpochMs | None = None
    # A dry run answers the question without recording a decision or an action. A check with
    # ``as_of`` asks about the past, so it is always a dry run.
    dry_run: bool = False


class CheckOut(ApiModel):
    # Null when nothing was recorded (a dry run): there is no stored decision to explain.
    decision_id: str | None
    result: Result
    reason: Reason
    action_id: str | None
    recorded: bool
    approval_required: bool
    path: list[PathHop]
    ignored: list[IgnoredInstruction]
    latency_ms: float


class ToolCallIn(ApiModel):
    agent_id: AgentId
    tool: str = Field(min_length=1, max_length=40)
    args: dict[str, Any] = Field(default_factory=dict)


class ApproveIn(ApiModel):
    by: PrincipalId
    approved: bool


class ExplainOut(ApiModel):
    decision: Decision
    action: Action
    used: list[dict[str, str]]
    narrative: str


# --- lineage ------------------------------------------------------------------------


class AffectedDecisionOut(ApiModel):
    decision_id: str
    result: Result
    reason: Reason
    action_type: str
    resource: str
    agent_id: str
    at: int


class BlastRadiusOut(ApiModel):
    instruction_id: str
    summaries: list[str]
    derived_instructions: list[str]
    delegations: list[str]
    decisions: list[AffectedDecisionOut]


class CheckResultOut(ApiModel):
    name: str
    ok: bool
    detail: str = ""


class VerifyOut(ApiModel):
    decision_id: str
    ok: bool
    checks: list[CheckResultOut]


class RelianceOut(ApiModel):
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
    flags: list[str]
    needs_review: bool


class QuarantineOut(ApiModel):
    instruction_ids: list[str]
    quarantined: bool


class ReplayChangeOut(ApiModel):
    decision_id: str
    action_type: str
    resource: str
    was_result: Result
    was_reason: Reason
    now_result: Result
    now_reason: Reason


class ReplayOut(ApiModel):
    instruction_id: str
    evaluated: int
    changes: list[ReplayChangeOut]
    unchanged: int


# --- console: graph, scenario runs, evaluation, demo --------------------------------


class GraphElement(ApiModel):
    """One Cytoscape element: a node (``data.id``) or an edge (``data.source``/``target``)."""

    group: str = Field(pattern=r"^(nodes|edges)$")
    data: dict[str, Any]
    classes: str


class GraphOut(ApiModel):
    elements: list[GraphElement]
    truncated: bool
    highlight: list[str] = Field(default_factory=list)


class ScenarioOut(ApiModel):
    id: str
    family: str
    description: str
    events: int
    attempts: int


class RunIn(ApiModel):
    scenario_id: str = Field(min_length=1, max_length=80)
    kinds: list[str] = Field(default_factory=lambda: ["naive", "mandate"], min_length=1)


class TimelineEntryOut(ApiModel):
    seq: int
    t: int
    event: str
    text: str
    agent: str | None = None
    tool: str | None = None
    expect: str | None = None
    status: str | None = None
    reason: str | None = None
    decision_id: str | None = None
    unauthorised: bool = False
    false_block: bool = False


class RunKindOut(ApiModel):
    kind: str
    timeline: list[TimelineEntryOut]
    unauthorised: int
    false_blocks: int
    held: int
    attempts: int


class RunOut(ApiModel):
    scenario_id: str
    description: str
    # The tenant Agent Mandate ran in; its decisions can be explained and drawn.
    tenant_id: str | None
    runs: list[RunKindOut]


class EvalOut(ApiModel):
    name: str
    metrics: dict[str, Any]
    report: str


# --- agent tokens ----------------------------------------------------------------------


class MintTokenIn(ApiModel):
    by: PrincipalId
    ttl_seconds: int | None = Field(default=None, ge=1, le=30 * 86_400)


class TokenOut(ApiModel):
    token: str
    token_id: TokenId
    agent_id: AgentId
    expires_at: int  # epoch seconds


class RevokeTokenIn(ApiModel):
    """Name the token by its id or give the token itself (then it must still be valid)."""

    by: PrincipalId
    token_id: TokenId | None = None
    token: str | None = Field(default=None, max_length=1000)


# --- approval links --------------------------------------------------------------------


class ApprovalLinkIn(ApiModel):
    by: PrincipalId  # the owner who will approve through the link
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400)


class ApprovalLinkOut(ApiModel):
    token: str
    expires_at: int  # epoch seconds
    path: str  # the console page that opens it, with the token in the fragment


class LinkIn(ApiModel):
    token: str = Field(min_length=1, max_length=1000)


class LinkResolveIn(LinkIn):
    approved: bool


# --- console accounts and the audit trail ----------------------------------------------


class LoginIn(ApiModel):
    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class PasswordChangeIn(ApiModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class PasswordResetIn(ApiModel):
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class MeOut(ApiModel):
    kind: Literal["user", "key"]
    id: str
    name: str
    email: str | None = None
    role: UserRole
    tenants: list[str] | None  # None means every tenant


class UserOut(ApiModel):
    id: str
    email: str
    name: str
    role: UserRole
    tenants: list[str] | None
    disabled: bool
    created_at: int
    updated_at: int
    last_login_at: int | None


class CreateUserIn(ApiModel):
    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    name: str = Field(min_length=1, max_length=80)
    role: UserRole
    tenants: list[str] | None = Field(default=None, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class UpdateUserIn(ApiModel):
    """Only the fields sent change; ``"tenants": null`` means every tenant."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: UserRole | None = None
    tenants: list[str] | None = Field(default=None, max_length=200)
    disabled: bool | None = None


class SessionOut(ApiModel):
    id: str
    created_at: int
    last_seen_at: int
    expires_at: int
    user_agent: str | None
    current: bool


class WebhookIn(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=2000)
    kind: WebhookKind
    events: list[WebhookEvent] = Field(
        default_factory=lambda: [WebhookEvent.APPROVAL_REQUESTED], min_length=1, max_length=5
    )


class WebhookPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    events: list[WebhookEvent] | None = Field(default=None, min_length=1, max_length=5)
    enabled: bool | None = None


class AuditPage(ApiModel):
    events: list[AuditEvent]
    next: str | None  # pass as ``before`` for the next, older page
