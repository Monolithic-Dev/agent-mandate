// Flow F: the latest evaluation, read from the results folder.

import { BarChart3, ChevronRight, FileText, FolderOpen, ShieldAlert, ShieldCheck, Timer, UserCheck } from "../icons";
import { motion } from "motion/react";

import { api } from "../api";
import { ErrorNote } from "../components/Bits";
import { formatRate, MetricsTable } from "../components/MetricsTable";
import { KIND_NAMES } from "../components/SplitRun";
import {
  Card,
  CardHead,
  EmptyState,
  ease,
  PageHeader,
  SkeletonRows,
  StatCard,
} from "../components/ui";
import type { KindMetrics, Rate } from "../types";
import { useLoad } from "../useLoad";

function share([n, total]: Rate): number {
  return total ? n / total : 0;
}

/** One horizontal bar per agent kind; the exact count is always printed beside it. */
function Bars({
  metrics,
  pick,
  goodWhenZero = true,
}: {
  metrics: Record<string, KindMetrics>;
  pick: (m: KindMetrics) => Rate;
  goodWhenZero?: boolean;
}) {
  return (
    <div className="bars">
      {Object.entries(metrics).map(([kind, m], index) => {
        const rate = pick(m);
        const value = share(rate);
        return (
          <div className="bar-row" key={kind}>
            <span style={{ fontWeight: kind === "mandate" ? 600 : 400 }}>
              {KIND_NAMES[kind] ?? kind}
            </span>
            <div className="bar-track" aria-hidden="true">
              <motion.div
                className={`bar-fill${goodWhenZero && value === 0 ? " good" : ""}`}
                initial={{ scaleX: 0 }}
                animate={{ scaleX: Math.max(value, 0.012) }}
                transition={{ duration: 0.7, ease, delay: 0.15 + index * 0.08 }}
              />
            </div>
            <span className="bar-value">
              {rate[0]} / {rate[1]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function Eval() {
  const latest = useLoad(() => api.evalLatest(), []);
  const data = latest.data;
  const ours = data?.metrics.mandate;
  const families = data
    ? [
        ...new Set(
          Object.values(data.metrics).flatMap((m) => Object.keys(m.unauthorised_by_family)),
        ),
      ].sort()
    : [];

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <BarChart3 size={14} aria-hidden="true" /> Evidence
          </>
        }
        title="Evaluation"
        description="Scripted scenarios, deterministic agents (no language model), a real graph database. Read the limits in the full report before quoting a number."
        actions={
          data && (
            <span className="chip">
              <FolderOpen size={13} aria-hidden="true" /> {data.name}
            </span>
          )
        }
      />
      <ErrorNote error={latest.error} />
      {latest.loading && !data && (
        <Card>
          <SkeletonRows rows={6} label="Loading the latest evaluation" />
        </Card>
      )}
      {data && ours && (
        <>
          <div className="stats">
            <StatCard
              icon={ShieldCheck}
              label="Unauthorised actions (Agent Mandate)"
              value={ours.unauthorised[0]}
              sub={`of ${ours.unauthorised[1]} probes that should not run`}
              tone="good"
            />
            <StatCard
              icon={UserCheck}
              label="Legitimate requests blocked"
              value={ours.false_blocks[0]}
              sub={`of ${ours.false_blocks[1]} legitimate probes`}
              tone="good"
              delay={0.04}
            />
            <StatCard
              icon={ShieldAlert}
              label="Explanations verified"
              value={formatRate(ours.verified ?? [0, 0]).split(" (")[0]}
              sub="every claim re-checked against the graph"
              tone="accent"
              delay={0.08}
            />
            <StatCard
              icon={Timer}
              label="Decision latency p50 / p95"
              value={
                ours.latency_p50_ms == null || ours.latency_p95_ms == null
                  ? "n/a"
                  : `${ours.latency_p50_ms.toFixed(1)} / ${ours.latency_p95_ms.toFixed(1)}`
              }
              sub="milliseconds, end to end"
              delay={0.12}
            />
          </div>

          <div
            style={{
              display: "grid",
              gap: 16,
              gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
              marginTop: 16,
            }}
          >
            <Card delay={0.08}>
              <CardHead
                icon={ShieldAlert}
                title="Unauthorised actions executed"
                hint="lower is better"
              />
              <div className="card-body">
                <Bars metrics={data.metrics} pick={(m) => m.unauthorised} />
              </div>
            </Card>
            <Card delay={0.12}>
              <CardHead
                icon={UserCheck}
                title="Legitimate requests blocked"
                hint="lower is better"
              />
              <div className="card-body">
                <Bars metrics={data.metrics} pick={(m) => m.false_blocks} />
              </div>
            </Card>
          </div>
        </>
      )}
      {data && (
        <>
          <div className="section">
            <Card className="card-flush" delay={0.14}>
              <CardHead icon={BarChart3} title="All metrics" hint="95% intervals in the report" />
              <MetricsTable metrics={data.metrics} />
            </Card>
          </div>

          <div className="section">
            <Card className="card-flush" delay={0.18}>
              <CardHead icon={ShieldAlert} title="Unauthorised actions by scenario family" />
              {families.length === 0 ? (
                <EmptyState title="None for any agent kind." />
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Family</th>
                        {Object.keys(data.metrics).map((kind) => (
                          <th
                            scope="col"
                            key={kind}
                            className={`num${kind === "mandate" ? " ours" : ""}`}
                          >
                            {KIND_NAMES[kind] ?? kind}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {families.map((family) => (
                        <tr key={family}>
                          <th scope="row">{family}</th>
                          {Object.entries(data.metrics).map(([kind, m]) => (
                            <td key={kind} className={`num${kind === "mandate" ? " ours" : ""}`}>
                              {m.unauthorised_by_family[family] ?? 0}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>

          {data.report && (
            <div className="section">
              <details className="card disclosure">
                <summary>
                  <ChevronRight size={16} aria-hidden="true" />
                  <FileText size={16} aria-hidden="true" /> Full report
                </summary>
                <pre className="report">{data.report}</pre>
              </details>
            </div>
          )}
        </>
      )}
    </div>
  );
}
