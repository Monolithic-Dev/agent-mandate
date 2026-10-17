// A tenant's activity: what its agents asked for and how it was decided, over the last day or
// week. A stacked bar per hour (or six hours) by outcome, with a hover tooltip and a table
// view; the outcome colours are validated for colour-blind separation in both themes (see
// styles.css, --chart-*), and every outcome also carries its word and icon.

import { Activity as ActivityIcon, Bot, Clock, Gavel, Inbox, ShieldCheck, Table } from "../icons";
import { motion } from "motion/react";
import { useMemo, useState } from "react";

import { api } from "../api";
import type { ActivitySummary, Agent } from "../types";
import { useLoad } from "../useLoad";
import { ErrorNote } from "./Bits";
import { EmptyState, SkeletonRows, StatCard } from "./ui";

const OUTCOMES = [
  { key: "allow", label: "Allowed" },
  { key: "confirm", label: "Needs approval" },
  { key: "deny", label: "Denied" },
] as const;

type OutcomeKey = (typeof OUTCOMES)[number]["key"];

const REASON_WORDS: Record<string, string> = {
  authorized: "a rule allows it",
  confirm_rule: "a rule says ask first",
  mixed_lineage: "partly untrusted authority",
  explicit_deny: "a rule forbids it",
  authority_revoked: "its rule was revoked",
  constraint_not_met: "over a rule's limit",
  no_authority_path: "no rule allows it",
  check_error: "the check failed",
};

const WIDTH = 720;
const HEIGHT = 200;
const PAD = { top: 10, right: 8, bottom: 26, left: 34 };
const GAP = 2; // the surface gap between stacked segments and between bars

/** The smallest "nice" axis top at or above ``value``: two equal whole-number steps of
 *  1, 1.5, 2, 2.5, 3, 4, 5, 6 or 8 × 10^k, so the middle gridline is a whole count too. */
export function niceMax(value: number): number {
  if (value <= 2) return 2;
  const raw = value / 2;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find(
      (s) => s * magnitude >= raw && Number.isInteger(s * magnitude),
    ) ?? 10;
  return step * magnitude * 2;
}

function timeLabel(ms: number, size: number): string {
  const date = new Date(ms);
  return size >= 6 * 3_600_000
    ? date.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })
    : date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function StackedBars({ data }: { data: ActivitySummary }) {
  const [hover, setHover] = useState<number | null>(null);
  const buckets = data.buckets;
  const totals = buckets.map((b) => b.allow + b.confirm + b.deny);
  const max = niceMax(Math.max(0, ...totals));
  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const slot = innerW / buckets.length;
  const barW = Math.max(2, slot - GAP * 2);
  const y = (value: number) => PAD.top + innerH - (value / max) * innerH;
  const ticks = [0, max / 2, max];
  const labelEvery = Math.ceil(buckets.length / 6);
  const hovered = hover === null ? null : buckets[hover];

  return (
    <div className="chart" onMouseLeave={() => setHover(null)}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Decisions per ${data.bucket_ms >= 6 * 3_600_000 ? "six hours" : "hour"}, by outcome. ${data.total} in all.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD.left - 6} y={y(t) + 4} className="chart-tick" textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        {buckets.map((bucket, index) => {
          const x = PAD.left + index * slot + (slot - barW) / 2;
          let base = 0;
          return (
            <g key={bucket.start} className={hover === index ? "bar-hot" : undefined}>
              {OUTCOMES.map(({ key }) => {
                const value = bucket[key];
                if (!value) return null;
                const top = y(base + value);
                const height = Math.max(0, y(base) - top - (base > 0 ? GAP : 0));
                base += value;
                return (
                  <motion.rect
                    key={key}
                    x={x}
                    width={barW}
                    className={`bar bar-${key}`}
                    rx={2}
                    initial={{ y: y(0), height: 0 }}
                    animate={{ y: top, height }}
                    transition={{ duration: 0.45, delay: index * 0.012, ease: [0.2, 0.8, 0.2, 1] }}
                  />
                );
              })}
              {/* The hit target: the whole column, wider than the bar. */}
              <rect
                x={PAD.left + index * slot}
                y={PAD.top}
                width={slot}
                height={innerH}
                className="bar-hit"
                onMouseEnter={() => setHover(index)}
                onFocus={() => setHover(index)}
                tabIndex={-1}
              />
              {index % labelEvery === 0 && (
                <text
                  x={PAD.left + index * slot + slot / 2}
                  y={HEIGHT - 8}
                  className="chart-tick"
                  textAnchor="middle"
                >
                  {timeLabel(bucket.start, data.bucket_ms)}
                </text>
              )}
            </g>
          );
        })}
        <line
          x1={PAD.left}
          x2={WIDTH - PAD.right}
          y1={y(0)}
          y2={y(0)}
          className="chart-axis"
        />
      </svg>
      {hovered && hover !== null && (
        <div
          className="chart-tooltip"
          role="status"
          style={{
            // Kept inside the card: centred on the bar, but never past either edge.
            left: `${Math.min(84, Math.max(16, ((PAD.left + (hover + 0.5) * slot) / WIDTH) * 100))}%`,
          }}
        >
          <strong>
            {timeLabel(hovered.start, data.bucket_ms)} –{" "}
            {timeLabel(hovered.start + data.bucket_ms, data.bucket_ms)}
          </strong>
          {OUTCOMES.map(({ key, label }) => (
            <span key={key} className="tooltip-row">
              <span className={`swatch swatch-${key}`} aria-hidden="true" /> {label}
              <span className="tooltip-value">{hovered[key]}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Ranked({
  title,
  rows,
  words,
}: {
  title: string;
  rows: { key: string; count: number }[];
  words?: (key: string) => string;
}) {
  const top = rows[0]?.count ?? 1;
  return (
    <section className="ranked" aria-label={title}>
      <h3 className="studio-h">{title}</h3>
      {rows.length === 0 && <p className="muted small">None in this window.</p>}
      <ul>
        {rows.map((row, index) => (
          <li key={row.key}>
            <span className="ranked-label">{words ? words(row.key) : row.key}</span>
            <span className="ranked-track" aria-hidden="true">
              <motion.span
                className="ranked-fill"
                initial={{ width: 0 }}
                animate={{ width: `${(row.count / top) * 100}%` }}
                transition={{ duration: 0.5, delay: index * 0.04 }}
              />
            </span>
            <span className="ranked-value">{row.count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ActivityPanel({ tid, waiting }: { tid: string; waiting: number }) {
  const [hours, setHours] = useState(24);
  const [asTable, setAsTable] = useState(false);
  const activity = useLoad(() => api.activity(tid, hours), [tid, hours]);
  const agents = useLoad(() => api.agents(tid), [tid]);
  const names = useMemo(
    () => Object.fromEntries((agents.data ?? []).map((a: Agent) => [a.id, a.name])),
    [agents.data],
  );
  const data = activity.data;
  const share = (key: OutcomeKey) =>
    data && data.total ? `${Math.round((data.results[key] / data.total) * 100)}% of decisions` : undefined;

  return (
    <div className="activity">
      <div className="activity-head">
        <div className="segmented" role="radiogroup" aria-label="Time range">
          {[
            { value: 24, label: "Last 24 hours" },
            { value: 168, label: "Last 7 days" },
          ].map((o) => (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={hours === o.value}
              className={hours === o.value ? "on" : undefined}
              onClick={() => setHours(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <button type="button" className="sm" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
          <Table size={14} aria-hidden="true" /> {asTable ? "Show the chart" : "Show as a table"}
        </button>
      </div>
      <ErrorNote error={activity.error} />
      {activity.loading && !data && <SkeletonRows rows={5} label="Loading activity" />}
      {data && (
        <>
          <div className="stats">
            <StatCard icon={Gavel} label="Decisions" value={data.total} tone="accent"
              sub={data.truncated ? "the newest 20,000 counted" : hours === 24 ? "in the last day" : "in the last week"} />
            <StatCard icon={ShieldCheck} label="Allowed" value={data.results.allow} tone="good" sub={share("allow")} delay={0.04} />
            <StatCard icon={Inbox} label="Held for approval" value={data.results.confirm} tone="warn"
              sub={`${waiting} waiting now`} delay={0.08} />
            <StatCard icon={ActivityIcon} label="Denied" value={data.results.deny} tone="bad" sub={share("deny")} delay={0.12} />
            <StatCard icon={Clock} label="Check time (p95)"
              value={data.latency_p95_ms == null ? "–" : `${data.latency_p95_ms} ms`}
              sub={data.latency_p50_ms == null ? "no checks yet" : `median ${data.latency_p50_ms} ms`} delay={0.16} />
          </div>

          {data.total === 0 ? (
            <EmptyState icon={Gavel} title="No decisions in this window">
              Every tool call an agent makes is decided and counted here.
            </EmptyState>
          ) : (
            <>
              <div className="chart-card">
                <div className="chart-head">
                  <h3 className="studio-h">Decisions over time</h3>
                  <ul className="legend" aria-label="Legend">
                    {OUTCOMES.map(({ key, label }) => (
                      <li key={key}>
                        <span className={`swatch swatch-${key}`} aria-hidden="true" /> {label}{" "}
                        <span className="muted">{data.results[key]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                {asTable ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">From</th>
                          {OUTCOMES.map((o) => (
                            <th key={o.key} scope="col">
                              {o.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.buckets
                          .filter((b) => b.allow + b.confirm + b.deny > 0)
                          .map((b) => (
                            <tr key={b.start}>
                              <td>{new Date(b.start).toLocaleString()}</td>
                              <td>{b.allow}</td>
                              <td>{b.confirm}</td>
                              <td>{b.deny}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <StackedBars data={data} />
                )}
              </div>
              <div className="ranked-grid">
                <Ranked title="Why" rows={data.reasons} words={(k) => REASON_WORDS[k] ?? k.replaceAll("_", " ")} />
                <Ranked title="What was asked" rows={data.actions} />
                <Ranked
                  title="Which agents"
                  rows={data.agents}
                  words={(k) => names[k] ?? k}
                />
              </div>
            </>
          )}
        </>
      )}
      <p className="muted small activity-foot">
        <Bot size={13} aria-hidden="true" /> Counted from the decisions recorded in this tenant's
        graph; dry runs from the rule studio are not recorded, so not counted.
      </p>
    </div>
  );
}
