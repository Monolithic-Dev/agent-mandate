// Response shapes of the REST API (docs/api-spec.md). Only the fields the console reads.

export type Result = "allow" | "confirm" | "deny";
export type LineageTrust = "trusted" | "mixed" | "untrusted";
export type InstructionStatus = "pending" | "active" | "revoked" | "superseded";

export interface Tenant {
  tenant_id: string;
  name: string;
  created_at: number;
}

export interface Principal {
  id: string;
  name: string;
  role: "owner" | "delegate" | "external" | string;
}

export interface Agent {
  id: string;
  name: string;
  kind: string;
}

export interface Instruction {
  id: string;
  effect: "allow" | "confirm" | "deny";
  text_span: string;
  status: InstructionStatus;
  created_at: number;
  activated_at: number | null;
  revoked_at: number | null;
  quarantined: boolean;
  lineage_trust: LineageTrust;
  activated_by?: string | null;
  activated_via?: "confirmed" | "auto" | null;
  valid_to?: number | null; // a time-limited rule stops applying then
}

export interface Scope {
  id: string;
  action_type: string;
  resource_pattern: string;
  constraints: { max_amount?: number | null };
}

export interface InstructionView {
  instruction: Instruction;
  scope: Scope;
  agent_id: string;
}

export interface PathHop {
  type: string;
  id: string;
  note: string;
}

export interface Decision {
  id: string;
  result: Result;
  reason: string;
  as_of: number;
  at: number;
  path: PathHop[];
  ignored: { id: string; why: string }[];
  latency_ms: number;
}

export interface Action {
  id: string;
  action_type: string;
  resource: string;
  status: string;
  at: number;
  args?: { tool?: string; tool_args?: Record<string, unknown> };
}

/** An action and why it was decided, from GET /actions (pending ones wait for approval). */
export interface ActionRow {
  action: Action;
  agent_id: string;
  decision_id: string | null;
}

/** What POST /tool-calls and the approval routes return. */
export interface ToolResult {
  status: "ok" | "confirmation_required" | "denied" | "error";
  reason?: string;
  message?: string;
  approval_id?: string;
  decision_id?: string;
}

export interface ApprovalLink {
  token: string;
  expires_at: number; // epoch seconds
  path: string; // /approve#<token>
}

/** What an approval link would approve, from POST /v1/approval-links/inspect. */
export interface LinkView {
  tenant_id: string;
  action: Action;
  agent: Agent;
  decision_id: string | null;
  narrative: string | null;
  approver: Principal;
  expires_at: number;
  pending: boolean;
}

export interface DecisionRow {
  decision: Decision;
  action: Action;
  agent_id: string;
}

export interface Explanation {
  decision: Decision;
  action: Action;
  used: { id: string; role: string }[];
  narrative: string;
}

export interface Verification {
  decision_id: string;
  ok: boolean;
  checks: { name: string; ok: boolean; detail: string }[];
}

export interface GraphElement {
  group: "nodes" | "edges";
  data: { id: string; label: string; caption?: string; source?: string; target?: string } & Record<
    string,
    unknown
  >;
  classes: string;
}

export interface Graph {
  elements: GraphElement[];
  truncated: boolean;
  highlight: string[];
}

export interface AffectedDecision {
  decision_id: string;
  result: Result;
  reason: string;
  action_type: string;
  resource: string;
  agent_id: string;
  at: number;
}

export interface BlastRadius {
  instruction_id: string;
  summaries: string[];
  derived_instructions: string[];
  delegations: string[];
  decisions: AffectedDecision[];
}

export interface Replay {
  instruction_id: string;
  evaluated: number;
  unchanged: number;
  changes: {
    decision_id: string;
    action_type: string;
    resource: string;
    was_result: Result;
    was_reason: string;
    now_result: Result;
    now_reason: string;
  }[];
}

export interface ScenarioInfo {
  id: string;
  family: string;
  description: string;
  events: number;
  attempts: number;
}

export type AttemptStatus = "executed" | "held" | "approved" | "denied";

export interface TimelineEntry {
  seq: number;
  t: number;
  event: string;
  text: string;
  agent: string | null;
  tool: string | null;
  expect: string | null;
  status: AttemptStatus | null;
  reason: string | null;
  decision_id: string | null;
  unauthorised: boolean;
  false_block: boolean;
}

export interface KindRun {
  kind: string;
  timeline: TimelineEntry[];
  unauthorised: number;
  false_blocks: number;
  held: number;
  attempts: number;
}

export interface Run {
  scenario_id: string;
  description: string;
  tenant_id: string | null;
  runs: KindRun[];
}

/** successes and total, as the evaluation writes them. */
export type Rate = [number, number];

export interface KindMetrics {
  runs: number;
  probes: number;
  unauthorised: Rate;
  false_blocks: Rate;
  confirm_correct: Rate;
  explained: Rate;
  verified?: Rate;
  lineage_found: Rate;
  replay_exact: Rate;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  unauthorised_by_family: Record<string, number>;
}

export interface EvalLatest {
  name: string;
  metrics: Record<string, KindMetrics>;
  report: string;
}

export interface SeedResult {
  tenant_id: string;
  owner_id: string;
  typo_rule_id: string;
  held_action_id: string;
  decision_ids: string[];
}

// --- console accounts and the audit trail ---------------------------------------------

export type UserRole = "viewer" | "operator" | "admin";

/** Who the console is signed in as: a user, or the server-side console key. */
export interface Me {
  kind: "user" | "key";
  id: string;
  name: string;
  email: string | null;
  role: UserRole;
  tenants: string[] | null; // null: every tenant
}

export interface ConsoleUser {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  tenants: string[] | null;
  disabled: boolean;
  created_at: number;
  updated_at: number;
  last_login_at: number | null;
}

/** A browser where the person is signed in. */
export interface SessionInfo {
  id: string;
  created_at: number;
  last_seen_at: number;
  expires_at: number;
  user_agent: string | null;
  current: boolean;
}

export type ActorKind = "user" | "key" | "link" | "cli" | "anonymous";
export type Outcome = "success" | "denied" | "failed";

export interface AuditEvent {
  id: string;
  at: number;
  actor_kind: ActorKind;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  method: string;
  route: string;
  tenant_id: string | null;
  target: string | null;
  status: number;
  outcome: Outcome;
  request_id: string | null;
}

export interface AuditPage {
  events: AuditEvent[];
  next: string | null;
}

export interface AuditFilter {
  tenant_id?: string;
  actor_id?: string;
  action?: string;
}

// --- the rule studio ------------------------------------------------------------------

export interface PreviewRule {
  effect: "allow" | "confirm" | "deny";
  action_type: string;
  resource_pattern: string;
  max_amount: number | null;
  valid_for_ms: number | null;
  valid_to: number | null;
  needs_confirmation: boolean;
  text_span: string;
}

export interface RuleConflict {
  rule: number;
  instruction_id: string;
  text_span: string;
  effect: "allow" | "confirm" | "deny";
  action_type: string;
  resource_pattern: string;
  max_amount: number | null;
  kind: "contradicts" | "duplicates" | "changes_limit";
}

export interface ImpactChange {
  agent_id: string;
  action_type: string;
  resource: string;
  amount: number | null;
  example_decision_id: string;
  was_result: Result;
  was_reason: string;
  now_result: Result;
  now_reason: string;
  result_changed: boolean;
}

export interface Preview {
  agent_ids: string[];
  rules: PreviewRule[];
  unparsed: string[];
  conflicts: RuleConflict[];
  evaluated: number;
  changes: ImpactChange[];
}

export interface CheckOutcome {
  decision_id: string | null;
  result: Result;
  reason: string;
  recorded: boolean;
  approval_required: boolean;
  path: PathHop[];
  ignored: { id: string; why: string }[];
  latency_ms: number;
}

export interface SaidOut {
  utterance_id: string;
  instructions: { instruction: Instruction; needs_confirmation: boolean }[];
  unparsed: string[];
}

// --- webhooks -------------------------------------------------------------------------

export interface WebhookInfo {
  id: string;
  tenant_id: string;
  name: string;
  url: string; // masked
  kind: "slack" | "json";
  events: string[];
  enabled: boolean;
  created_at: number;
  created_by: string | null;
  last_delivery_at: number | null;
  last_ok: boolean | null;
  failures: number;
  secret?: string; // only when just created
}

export interface DeliveryInfo {
  id: string;
  webhook_id: string;
  event: string;
  at: number;
  ok: boolean;
  attempts: number;
  status: number | null;
  error: string | null;
  duration_ms: number;
  subject: string | null;
}

// --- activity -------------------------------------------------------------------------

export interface ActivitySummary {
  since: number;
  until: number;
  bucket_ms: number;
  total: number;
  truncated: boolean;
  results: { allow: number; confirm: number; deny: number };
  buckets: { start: number; allow: number; confirm: number; deny: number }[];
  reasons: { key: string; count: number }[];
  actions: { key: string; count: number }[];
  agents: { key: string; count: number }[];
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_max_ms: number | null;
}
