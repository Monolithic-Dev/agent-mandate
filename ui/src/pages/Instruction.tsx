// Flow E: a rule's blast radius, a replay without it, and quarantine.

import { ArrowRight, Gavel, GitBranch, History, Lock, ScrollText, Unlock, Workflow } from "../icons";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../api";
import { useAuth } from "../auth";
import { Chip, ErrorNote, ResultBadge, shortTime } from "../components/Bits";
import { GraphView } from "../components/GraphView";
import {
  Card,
  CardHead,
  PageHeader,
  SkeletonRows,
  Spinner,
  StatCard,
  useConfirm,
} from "../components/ui";
import { useElementLinks } from "../graphLinks";
import type { Replay } from "../types";
import { useLoad } from "../useLoad";

export function InstructionPage() {
  const { tid = "", iid = "" } = useParams();
  const rules = useLoad(() => api.instructions(tid), [tid]);
  const principals = useLoad(() => api.principals(tid), [tid]);
  const radius = useLoad(() => api.blastRadius(tid, iid), [tid, iid]);
  const graph = useLoad(() => api.graph(tid), [tid]);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [ask, dialog] = useConfirm();
  const select = useElementLinks(tid);
  const { can } = useAuth();
  const admin = can("admin");

  const view = rules.data?.find((r) => r.instruction.id === iid);
  const rule = view?.instruction;
  const owner = principals.data?.find((p) => p.role === "owner");

  const affected = useMemo(() => {
    const r = radius.data;
    if (!r) return new Set<string>();
    return new Set([
      r.instruction_id,
      ...r.summaries,
      ...r.derived_instructions,
      ...r.delegations,
      ...r.decisions.map((d) => d.decision_id),
    ]);
  }, [radius.data]);

  async function run(label: string, task: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await task();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(null);
    }
  }

  const doReplay = () =>
    run("replay", async () => {
      const result = await api.replay(tid, iid);
      setReplay(result);
      toast.info(`Replay finished: ${result.changes.length} of ${result.evaluated} flip.`);
    });

  const toggleQuarantine = () => {
    if (!owner || !rule) return;
    const releasing = rule.quarantined;
    ask({
      title: releasing ? "Release this rule from quarantine?" : "Quarantine this rule?",
      description: releasing
        ? "The rule and everything derived from it can apply again from the next check."
        : "The rule and every rule derived from it stop applying from the next check. You can release them later.",
      detail: `“${rule.text_span}”`,
      confirmLabel: releasing ? "Release" : "Quarantine",
      tone: releasing ? "default" : "danger",
      icon: releasing ? Unlock : Lock,
      run: () =>
        run("quarantine", async () => {
          const done = releasing
            ? await api.release(tid, iid, owner.id)
            : await api.quarantine(tid, iid, owner.id);
          toast.success(
            `${releasing ? "Released" : "Quarantined"} ${done.instruction_ids.length} rule${done.instruction_ids.length === 1 ? "" : "s"}.`,
          );
          rules.reload();
          graph.reload();
        }),
    });
  };

  return (
    <div className="page">
      <ErrorNote error={rules.error ?? error} />
      {rules.loading && !rules.data && (
        <Card>
          <SkeletonRows rows={4} label="Loading the rule" />
        </Card>
      )}
      {rules.data && !view && <p>No such rule in this tenant.</p>}
      {rule && view && (
        <PageHeader
          eyebrow={
            <>
              <ScrollText size={14} aria-hidden="true" /> Rule
            </>
          }
          title={<>“{rule.text_span}”</>}
          description={
            <>
              <span className="chips">
                <Chip kind={`effect-${rule.effect}`}>{rule.effect}</Chip>
                <Chip kind={`state-${rule.status}`}>{rule.status}</Chip>
                <Chip kind={`trust-${rule.lineage_trust}`}>{rule.lineage_trust} origin</Chip>
                {rule.quarantined && <Chip kind="state-quarantined">quarantined</Chip>}
                <span className="mono small">
                  {view.scope.action_type} on {view.scope.resource_pattern}
                  {view.scope.constraints?.max_amount != null &&
                    ` up to ${view.scope.constraints.max_amount}`}
                </span>
              </span>
              <span className="muted small" style={{ display: "block", marginTop: 6 }}>
                Created {shortTime(rule.created_at)}
                {rule.activated_at != null && ` · active since ${shortTime(rule.activated_at)}`}
                {rule.activated_via && ` (${rule.activated_via})`}
                {rule.revoked_at != null && ` · revoked ${shortTime(rule.revoked_at)}`}
              </span>
            </>
          }
          actions={
            <>
              <button
                type="button"
                className="primary"
                onClick={() => void doReplay()}
                disabled={
                  busy !== null || !admin || !radius.data || radius.data.decisions.length === 0
                }
                title={admin ? undefined : "Replaying needs the admin role"}
              >
                {busy === "replay" ? <Spinner /> : <History size={15} aria-hidden="true" />}
                {busy === "replay" ? "Replaying…" : "Replay without this rule"}
              </button>
              <button
                type="button"
                className={rule.quarantined ? undefined : "danger"}
                onClick={toggleQuarantine}
                disabled={busy !== null || !owner || !admin}
                title={
                  !admin
                    ? "Quarantine needs the admin role"
                    : owner
                      ? undefined
                      : "This tenant has no owner"
                }
              >
                {rule.quarantined ? (
                  <Unlock size={15} aria-hidden="true" />
                ) : (
                  <Lock size={15} aria-hidden="true" />
                )}
                {busy === "quarantine"
                  ? "Working…"
                  : rule.quarantined
                    ? "Release from quarantine"
                    : "Quarantine (with everything derived from it)"}
              </button>
            </>
          }
        />
      )}

      <ErrorNote error={radius.error} />
      {radius.data && (
        <div className="stats">
          <StatCard
            icon={Gavel}
            label="Decisions that used it"
            value={radius.data.decisions.length}
            tone="accent"
          />
          <StatCard
            icon={Workflow}
            label="Rules derived from it"
            value={radius.data.derived_instructions.length}
            delay={0.04}
          />
          <StatCard
            icon={GitBranch}
            label="Delegations resting on it"
            value={radius.data.delegations.length}
            delay={0.08}
          />
          <StatCard
            icon={History}
            label="Would change on replay"
            value={replay ? replay.changes.length : "–"}
            tone={replay && replay.changes.length > 0 ? "warn" : "neutral"}
            sub={replay ? `of ${replay.evaluated} replayed` : "run a replay to see"}
            delay={0.12}
          />
        </div>
      )}

      <div className="section">
        <Card className="card-flush">
          <CardHead
            icon={Gavel}
            title="Blast radius"
            hint={
              radius.data
                ? `${radius.data.decisions.length} decisions used this rule${
                    radius.data.derived_instructions.length > 0
                      ? `, ${radius.data.derived_instructions.length} rules derive from it`
                      : ""
                  }${
                    radius.data.delegations.length > 0
                      ? `, ${radius.data.delegations.length} delegations rest on it`
                      : ""
                  }.`
                : undefined
            }
          />
          {radius.loading && !radius.data && (
            <SkeletonRows rows={4} label="Tracing what this rule touched" />
          )}
          {replay && (
            <motion.div
              className="callout callout-info"
              role="status"
              style={{ margin: 14 }}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <History size={16} aria-hidden="true" />
              <span>
                Replayed {replay.evaluated} decisions on a throwaway copy: {replay.changes.length}{" "}
                would change, {replay.unchanged} would not. Nothing live was modified.
              </span>
            </motion.div>
          )}
          {radius.data && radius.data.decisions.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Decision</th>
                    <th scope="col">Result</th>
                    <th scope="col">After replay</th>
                  </tr>
                </thead>
                <tbody>
                  {radius.data.decisions.map((d, index) => {
                    const change = replay?.changes.find((c) => c.decision_id === d.decision_id);
                    return (
                      <motion.tr
                        key={d.decision_id}
                        className={change ? "lit" : undefined}
                        animate={change ? { x: [0, 4, 0] } : { x: 0 }}
                        transition={{ duration: 0.35, delay: index * 0.05 }}
                      >
                        <td>
                          <Link to={`/tenants/${tid}/decisions/${d.decision_id}`}>
                            {d.action_type} {d.resource}
                          </Link>
                        </td>
                        <td>
                          <ResultBadge result={d.result} />{" "}
                          <span className="muted small">{d.reason.replaceAll("_", " ")}</span>
                        </td>
                        <td>
                          {!replay && <span className="muted">not replayed</span>}
                          {replay && !change && <span className="muted">unchanged</span>}
                          {change && (
                            <span className="chips">
                              <ArrowRight size={14} aria-hidden="true" />
                              <ResultBadge result={change.now_result} />
                              <span className="muted small">
                                {change.now_reason.replaceAll("_", " ")}
                              </span>
                            </span>
                          )}
                        </td>
                      </motion.tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <div className="section">
        <div className="section-head">
          <h2>On the graph</h2>
          <span className="hint">everything this rule touched is highlighted</span>
        </div>
        <ErrorNote error={graph.error} />
        {graph.loading && !graph.data && <div className="card skeleton" style={{ height: 460 }} />}
        {graph.data && (
          <GraphView
            elements={graph.data.elements}
            truncated={graph.data.truncated}
            highlight={affected}
            onSelect={select}
          />
        )}
      </div>
      {dialog}
    </div>
  );
}
