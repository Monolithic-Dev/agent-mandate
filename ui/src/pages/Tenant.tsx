// One tenant: what waits for the owner's approval, its rules (confirm, revoke), its decision
// log and its graph, in tabs; it updates live while open.

import { Activity, BellRing, Building2, CircleCheck, CircleSlash, Gavel, Inbox, ListChecks, Network, ScrollText, ShieldAlert, Wand2 } from "../icons";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorNote, relativeTime, ResultBadge, shortTime } from "../components/Bits";
import { ActivityPanel } from "../components/ActivityPanel";
import { GraphExplorer } from "../components/GraphExplorer";
import { describeCall, PendingList } from "../components/PendingList";
import { RulesList } from "../components/RulesList";
import { WebhooksPanel } from "../components/WebhooksPanel";
import {
  Card,
  EmptyState,
  PageHeader,
  SkeletonRows,
  StatCard,
  Tabs,
  useConfirm,
} from "../components/ui";
import type { ApprovalLink } from "../types";
import { type LiveStatus, useLiveEvents } from "../useLiveEvents";
import { useLoad } from "../useLoad";

const TABS = ["approvals", "rules", "decisions", "activity", "graph", "alerts"] as const;
type Tab = (typeof TABS)[number];

const LIVE_WORD: Record<LiveStatus, string> = {
  off: "",
  connecting: "connecting…",
  live: "live",
  reconnecting: "reconnecting…",
};

function LiveBadge({ status }: { status: LiveStatus }) {
  if (status === "off") return null;
  return (
    <span
      className={`chip live live-${status}`}
      title="Updates appear here as agents act, without reloading"
    >
      <span className="live-dot" aria-hidden="true" /> {LIVE_WORD[status]}
    </span>
  );
}

export function Tenant() {
  const { tid = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.includes(params.get("tab") as Tab)
    ? (params.get("tab") as Tab)
    : "approvals";
  const principals = useLoad(() => api.principals(tid), [tid]);
  const agents = useLoad(() => api.agents(tid), [tid]);
  const pending = useLoad(() => api.pendingActions(tid), [tid]);
  const rules = useLoad(() => api.instructions(tid), [tid]);
  const decisions = useLoad(() => api.decisions(tid), [tid]);
  const graph = useLoad(() => api.graph(tid), [tid]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [links, setLinks] = useState<Record<string, ApprovalLink>>({});
  const [ask, dialog] = useConfirm();
  const { can } = useAuth();
  const admin = can("admin");

  const owner = principals.data?.find((p) => p.role === "owner");
  const agentNames = Object.fromEntries((agents.data ?? []).map((a) => [a.id, a.name]));
  const setTab = (next: string) =>
    setParams(next === "approvals" ? {} : { tab: next }, { replace: true });

  const live = useLiveEvents(tid, {
    decisions: () => {
      decisions.reload();
      graph.reload();
    },
    approvals: ({ added }) => {
      pending.reload();
      if (added.length > 0) {
        toast.info(
          added.length === 1
            ? "A new action is waiting for approval."
            : `${added.length} new actions are waiting for approval.`,
          tab === "approvals"
            ? undefined
            : { action: { label: "Review", onClick: () => setTab("approvals") } },
        );
      }
    },
    rules: () => {
      rules.reload();
      graph.reload();
    },
  });

  async function act(key: string, run: () => Promise<unknown>, done?: string) {
    setBusy(key);
    setError(null);
    try {
      await run();
      if (done) toast.success(done);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(null);
    }
  }

  const confirmRule = (id: string) =>
    owner &&
    void act(
      id,
      async () => {
        await api.confirm(tid, id, owner.id);
        rules.reload();
        graph.reload();
      },
      "Rule confirmed: it applies from the next check.",
    );

  const revokeRule = (id: string) => {
    const view = rules.data?.find((r) => r.instruction.id === id);
    ask({
      title: "Revoke this rule?",
      description: "It stops applying from the next check. Past decisions keep their record.",
      detail: view ? `“${view.instruction.text_span}”` : id,
      confirmLabel: "Revoke rule",
      tone: "danger",
      icon: CircleSlash,
      run: () =>
        owner &&
        act(
          id,
          async () => {
            await api.revoke(tid, id, owner.id);
            rules.reload();
            graph.reload();
          },
          "Rule revoked.",
        ),
    });
  };

  const resolve = (actionId: string, approved: boolean) => {
    const row = pending.data?.find((r) => r.action.id === actionId);
    const call = row ? describeCall(row.action) : actionId;
    ask({
      title: approved ? "Approve and run this action?" : "Decline this action?",
      description: approved
        ? "It runs now, as the agent asked. Your approval is recorded on the graph."
        : "It will not run. The agent is told it was declined.",
      detail: call,
      confirmLabel: approved ? "Approve and run" : "Decline action",
      tone: approved ? "default" : "danger",
      icon: approved ? CircleCheck : CircleSlash,
      run: () =>
        owner &&
        act(actionId, async () => {
          try {
            const result = await api.resolveAction(tid, actionId, owner.id, approved);
            if (result.status === "ok") toast.success(`Approved: ${call} ran.`);
            else if (result.status === "denied") toast(`Declined: ${call} did not run.`);
            else toast.error(`Approved, but ${call} failed: ${result.message ?? "error"}.`);
            decisions.reload();
            graph.reload();
          } finally {
            pending.reload();
          }
        }),
    });
  };

  const makeLink = (actionId: string) =>
    owner &&
    void act(actionId, async () => {
      const link = await api.approvalLink(tid, actionId, owner.id);
      setLinks((current) => ({ ...current, [actionId]: link }));
    });

  const uniqueRules = new Map((rules.data ?? []).map((r) => [r.instruction.id, r.instruction]));
  const activeRules = [...uniqueRules.values()].filter((r) => r.status === "active").length;
  const untrusted = [...uniqueRules.values()].filter((r) => r.lineage_trust === "untrusted").length;
  const waiting = pending.data?.length ?? 0;

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <Building2 size={14} aria-hidden="true" /> Tenant
          </>
        }
        title={
          <span className="mono" style={{ fontSize: "0.9em" }}>
            {tid}
          </span>
        }
        badge={<LiveBadge status={live} />}
        actions={
          <Link to={`/tenants/${tid}/studio`} className="btn">
            <Wand2 size={15} aria-hidden="true" /> Rule studio
          </Link>
        }
        description={
          owner && !admin ? (
            <span className="small muted">
              Read-only: your role can see this tenant but not confirm, revoke or approve.
            </span>
          ) : owner ? (
            <span className="small muted">
              Acting as the owner {owner.name} ({owner.id}).
            </span>
          ) : principals.data ? (
            <span className="small muted">
              This tenant has no owner, so rules cannot be confirmed or revoked.
            </span>
          ) : undefined
        }
      />
      <ErrorNote error={principals.error ?? error} />

      <div className="stats" style={{ marginBottom: 22 }}>
        <StatCard
          icon={Inbox}
          label="Waiting for approval"
          value={pending.data ? waiting : "–"}
          tone={waiting > 0 ? "warn" : "neutral"}
          sub={waiting > 0 ? "the owner decides" : "nothing held"}
        />
        <StatCard
          icon={ScrollText}
          label="Active rules"
          value={rules.data ? activeRules : "–"}
          tone="good"
          sub={rules.data ? `${uniqueRules.size} rules in all` : undefined}
          delay={0.04}
        />
        <StatCard
          icon={Gavel}
          label="Decisions"
          value={decisions.data ? decisions.data.length : "–"}
          tone="accent"
          sub={
            decisions.data?.[0]
              ? `latest ${relativeTime(decisions.data[0].decision.at)}`
              : "none yet"
          }
          delay={0.08}
        />
        <StatCard
          icon={ShieldAlert}
          label="Untrusted rules held inert"
          value={rules.data ? untrusted : "–"}
          tone={untrusted > 0 ? "bad" : "neutral"}
          sub="drawn from content, never authority"
          delay={0.12}
        />
      </div>

      <Tabs
        label="Tenant sections"
        value={tab}
        onChange={setTab}
        items={[
          {
            value: "approvals",
            label: "Waiting for approval",
            icon: Inbox,
            count: waiting,
            hot: true,
            content: (
              <Card className="card-flush">
                <ErrorNote error={pending.error} />
                {pending.loading && !pending.data ? (
                  <SkeletonRows rows={3} label="Loading held actions" />
                ) : (
                  <PendingList
                    tenantId={tid}
                    rows={pending.data ?? []}
                    agentNames={agentNames}
                    canAct={!!owner && admin}
                    busy={busy}
                    links={links}
                    onResolve={resolve}
                    onLink={makeLink}
                  />
                )}
              </Card>
            ),
          },
          {
            value: "rules",
            label: "Rules",
            icon: ListChecks,
            count: rules.data ? uniqueRules.size : undefined,
            content: (
              <Card className="card-flush">
                <ErrorNote error={rules.error} />
                {rules.loading && !rules.data ? (
                  <SkeletonRows rows={4} label="Loading rules" />
                ) : (
                  <RulesList
                    tenantId={tid}
                    rows={rules.data ?? []}
                    canAct={!!owner && admin}
                    busy={busy}
                    onConfirm={confirmRule}
                    onRevoke={revokeRule}
                  />
                )}
              </Card>
            ),
          },
          {
            value: "decisions",
            label: "Decisions",
            icon: Gavel,
            count: decisions.data?.length,
            content: (
              <Card className="card-flush">
                <ErrorNote error={decisions.error} />
                {decisions.loading && !decisions.data && (
                  <SkeletonRows rows={5} label="Loading decisions" />
                )}
                {decisions.data && decisions.data.length === 0 && (
                  <EmptyState icon={Gavel} title="No decisions yet.">
                    Every tool call an agent makes is decided and recorded here.
                  </EmptyState>
                )}
                {decisions.data && decisions.data.length > 0 && (
                  <div className="table-wrap">
                    <table className="stack">
                      <thead>
                        <tr>
                          <th scope="col">When</th>
                          <th scope="col">Action</th>
                          <th scope="col">Result</th>
                          <th scope="col">Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {decisions.data.map(({ decision, action }) => (
                          <tr key={decision.id}>
                            <td
                              className="muted small"
                              title={shortTime(decision.at)}
                              data-label="When"
                            >
                              {relativeTime(decision.at)}
                            </td>
                            <td data-label="Action">
                              <Link to={`/tenants/${tid}/decisions/${decision.id}`}>
                                {action.action_type} {action.resource}
                              </Link>
                            </td>
                            <td data-label="Result">
                              <ResultBadge result={decision.result} />
                            </td>
                            <td className="muted" data-label="Reason">
                              {decision.reason.replaceAll("_", " ")}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            ),
          },
          {
            value: "activity",
            label: "Activity",
            icon: Activity,
            content: (
              <Card className="card-pad">
                <ActivityPanel tid={tid} waiting={waiting} />
              </Card>
            ),
          },
          {
            value: "graph",
            label: "Graph",
            icon: Network,
            content: (
              <>
                <ErrorNote error={graph.error} />
                {graph.loading && !graph.data && (
                  <div className="card skeleton" style={{ height: 520 }} />
                )}
                {graph.data && (
                  <GraphExplorer
                    tid={tid}
                    elements={graph.data.elements}
                    truncated={graph.data.truncated}
                  />
                )}
              </>
            ),
          },
          ...(admin
            ? [
                {
                  value: "alerts",
                  label: "Alerts",
                  icon: BellRing,
                  content: (
                    <Card className="card-pad">
                      <WebhooksPanel tid={tid} />
                    </Card>
                  ),
                },
              ]
            : []),
        ]}
      />
      {dialog}
    </div>
  );
}
