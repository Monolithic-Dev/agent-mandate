// A typed client for the REST API. Requests go to /v1 on this origin. Either the dev
// server's proxy (or nginx in Docker) adds a console key, so it never appears in the
// browser, or the person signs in and the API sets an HttpOnly session cookie.
//
// Every request carries X-Mandate-Client: console. With a session cookie the API refuses
// any change without it, which is what stops another site from forging one.

import type {
  ActionRow,
  ActivitySummary,
  Agent,
  ApprovalLink,
  AuditFilter,
  AuditPage,
  BlastRadius,
  CheckOutcome,
  ConsoleUser,
  DecisionRow,
  EvalLatest,
  Explanation,
  Graph,
  Instruction,
  InstructionView,
  LinkView,
  Me,
  SessionInfo,
  Preview,
  Principal,
  Replay,
  Run,
  SaidOut,
  ScenarioInfo,
  SeedResult,
  Tenant,
  ToolResult,
  UserRole,
  Verification,
  DeliveryInfo,
  WebhookInfo,
} from "./types";

/** Sent when the API says the session has ended, so the console can ask to sign in again. */
export const SIGNED_OUT_EVENT = "mandate-signed-out";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** Turn a failed response into an ApiError, using the API's error body when there is one. */
export function toApiError(status: number, statusText: string, body: unknown): ApiError {
  const error = (body as { error?: { code?: string; message?: string; request_id?: string } })
    ?.error;
  return new ApiError(
    status,
    error?.code ?? `http_${status}`,
    error?.message ?? (statusText || "request failed"),
    error?.request_id,
  );
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Mandate-Client": "console" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const signIn = path.startsWith("/v1/auth/") || path.startsWith("/v1/approval-links/");
    if (response.status === 401 && !signIn && typeof window !== "undefined") {
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    }
    throw toApiError(response.status, response.statusText, data);
  }
  return data as T;
}

const tenant = (id: string) => `/v1/tenants/${encodeURIComponent(id)}`;
const q = (params: Record<string, string | number | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][];
  return entries.length ? `?${new URLSearchParams(entries)}` : "";
};

export const api = {
  tenants: () => request<Tenant[]>("GET", "/v1/tenants"),
  principals: (t: string) => request<Principal[]>("GET", `${tenant(t)}/principals`),
  agents: (t: string) => request<Agent[]>("GET", `${tenant(t)}/agents`),
  instructions: (t: string) => request<InstructionView[]>("GET", `${tenant(t)}/instructions`),
  decisions: (t: string, limit = 100) =>
    request<DecisionRow[]>("GET", `${tenant(t)}/decisions${q({ limit })}`),
  explain: (t: string, d: string) =>
    request<Explanation>("GET", `${tenant(t)}/decisions/${encodeURIComponent(d)}/explain`),
  verify: (t: string, d: string) =>
    request<Verification>("GET", `${tenant(t)}/decisions/${encodeURIComponent(d)}/verify`),
  graph: (t: string, highlight?: string) =>
    request<Graph>("GET", `${tenant(t)}/graph${q({ highlight })}`),
  confirm: (t: string, i: string, by: string) =>
    request<Instruction>("POST", `${tenant(t)}/instructions/${encodeURIComponent(i)}/confirm`, {
      by,
    }),
  revoke: (t: string, i: string, by: string) =>
    request<Instruction>("POST", `${tenant(t)}/instructions/${encodeURIComponent(i)}/revoke`, {
      by,
    }),
  blastRadius: (t: string, i: string) =>
    request<BlastRadius>("GET", `${tenant(t)}/instructions/${encodeURIComponent(i)}/blast-radius`),
  replay: (t: string, i: string) =>
    request<Replay>("POST", `${tenant(t)}/instructions/${encodeURIComponent(i)}/replay`, {}),
  quarantine: (t: string, i: string, by: string) =>
    request<{ instruction_ids: string[] }>(
      "POST",
      `${tenant(t)}/instructions/${encodeURIComponent(i)}/quarantine`,
      { by },
    ),
  release: (t: string, i: string, by: string) =>
    request<{ instruction_ids: string[] }>(
      "DELETE",
      `${tenant(t)}/instructions/${encodeURIComponent(i)}/quarantine${q({ by })}`,
    ),
  pendingActions: (t: string) =>
    request<ActionRow[]>("GET", `${tenant(t)}/actions${q({ status: "pending" })}`),
  resolveAction: (t: string, a: string, by: string, approved: boolean) =>
    request<ToolResult>("POST", `${tenant(t)}/actions/${encodeURIComponent(a)}/approve`, {
      by,
      approved,
    }),
  approvalLink: (t: string, a: string, by: string) =>
    request<ApprovalLink>("POST", `${tenant(t)}/actions/${encodeURIComponent(a)}/approval-link`, {
      by,
    }),
  // The link is the credential: these two need no API key, and the token travels in the body.
  inspectLink: (token: string) =>
    request<LinkView>("POST", "/v1/approval-links/inspect", { token }),
  resolveLink: (token: string, approved: boolean) =>
    request<ToolResult>("POST", "/v1/approval-links/resolve", { token, approved }),
  // The rule studio: preview a sentence, say it, and try an action without recording it.
  preview: (t: string, principal_id: string, text: string, agent_ids?: string[]) =>
    request<Preview>("POST", `${tenant(t)}/utterances/preview`, { principal_id, text, agent_ids }),
  say: (t: string, principal_id: string, text: string, agent_ids?: string[]) =>
    request<SaidOut>("POST", `${tenant(t)}/utterances`, {
      principal_id,
      text,
      channel: "owner_direct",
      agent_ids,
    }),
  simulate: (
    t: string,
    body: { agent_id: string; action_type: string; resource: string; args: Record<string, unknown> },
  ) => request<CheckOutcome>("POST", `${tenant(t)}/check`, { ...body, dry_run: true }),
  activity: (t: string, hours = 24) =>
    request<ActivitySummary>("GET", `${tenant(t)}/activity${q({ hours })}`),
  // Webhooks (admins): tell the owner, in Slack or a JSON endpoint, that an action waits.
  webhooks: (t: string) => request<WebhookInfo[]>("GET", `${tenant(t)}/webhooks`),
  createWebhook: (t: string, body: { name: string; url: string; kind: "slack" | "json" }) =>
    request<WebhookInfo>("POST", `${tenant(t)}/webhooks`, body),
  updateWebhook: (t: string, id: string, body: { enabled?: boolean; name?: string }) =>
    request<WebhookInfo>("PATCH", `${tenant(t)}/webhooks/${encodeURIComponent(id)}`, body),
  deleteWebhook: (t: string, id: string) =>
    request<null>("DELETE", `${tenant(t)}/webhooks/${encodeURIComponent(id)}`),
  testWebhook: (t: string, id: string) =>
    request<DeliveryInfo>("POST", `${tenant(t)}/webhooks/${encodeURIComponent(id)}/test`),
  deliveries: (t: string, id: string) =>
    request<DeliveryInfo[]>("GET", `${tenant(t)}/webhooks/${encodeURIComponent(id)}/deliveries`),
  scenarios: () => request<ScenarioInfo[]>("GET", "/v1/scenarios"),
  run: (scenarioId: string, kinds: string[] = ["naive", "mandate"]) =>
    request<Run>("POST", "/v1/runs", { scenario_id: scenarioId, kinds }),
  evalLatest: () => request<EvalLatest>("GET", "/v1/eval/latest"),
  resetDemo: () => request<SeedResult>("POST", "/v1/demo/reset"),

  // Signing in, and the signed-in person's own account.
  me: () => request<Me>("GET", "/v1/auth/me"),
  login: (email: string, password: string) =>
    request<Me>("POST", "/v1/auth/login", { email, password }),
  logout: () => request<null>("POST", "/v1/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    request<Me>("POST", "/v1/auth/password", { current_password, new_password }),
  endMySessions: () => request<null>("POST", "/v1/auth/sessions/end"),
  mySessions: () => request<SessionInfo[]>("GET", "/v1/auth/sessions"),
  endMySession: (id: string) =>
    request<null>("DELETE", `/v1/auth/sessions/${encodeURIComponent(id)}`),

  // Users (admins with every tenant) and the audit trail (admins).
  users: () => request<ConsoleUser[]>("GET", "/v1/users"),
  createUser: (body: {
    email: string;
    name: string;
    role: UserRole;
    tenants: string[] | null;
    password: string;
  }) => request<ConsoleUser>("POST", "/v1/users", body),
  updateUser: (
    id: string,
    body: Partial<{ name: string; role: UserRole; tenants: string[] | null; disabled: boolean }>,
  ) => request<ConsoleUser>("PATCH", `/v1/users/${encodeURIComponent(id)}`, body),
  resetPassword: (id: string, password: string) =>
    request<ConsoleUser>("POST", `/v1/users/${encodeURIComponent(id)}/password`, { password }),
  endSessions: (id: string) =>
    request<ConsoleUser>("POST", `/v1/users/${encodeURIComponent(id)}/sessions/end`),
  audit: (filter: AuditFilter = {}, before?: string, limit = 50) =>
    request<AuditPage>("GET", `/v1/audit${q({ ...filter, before, limit })}`),
  auditExportUrl: (filter: AuditFilter = {}) => `/v1/audit/export${q({ ...filter })}`,
};
