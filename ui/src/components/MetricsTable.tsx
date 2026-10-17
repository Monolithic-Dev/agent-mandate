// The evaluation's headline table, read from metrics.json (one column per agent kind).

import type { KindMetrics, Rate } from "../types";
import { KIND_NAMES } from "./SplitRun";

export function formatRate([successes, total]: Rate): string {
  if (!total) return "n/a";
  return `${successes} of ${total} (${((100 * successes) / total).toFixed(1)}%)`;
}

const ROWS: { label: string; value: (m: KindMetrics) => string; better?: string }[] = [
  {
    label: "Unauthorised actions executed",
    value: (m) => formatRate(m.unauthorised),
    better: "lower is better",
  },
  {
    label: "Legitimate requests blocked",
    value: (m) => formatRate(m.false_blocks),
    better: "lower is better",
  },
  { label: "Held when confirmation was required", value: (m) => formatRate(m.confirm_correct) },
  { label: "Decisions with a complete explanation", value: (m) => formatRate(m.explained) },
  {
    label: "Explanations verified against the graph",
    value: (m) => (m.verified ? formatRate(m.verified) : "n/a"),
  },
  { label: "Lineage: affected decisions found", value: (m) => formatRate(m.lineage_found) },
  { label: "Lineage: replay matched the oracle", value: (m) => formatRate(m.replay_exact) },
  {
    label: "Decision latency p50 / p95",
    value: (m) =>
      m.latency_p50_ms == null || m.latency_p95_ms == null
        ? "n/a"
        : `${m.latency_p50_ms.toFixed(1)} / ${m.latency_p95_ms.toFixed(1)} ms`,
  },
];

export function MetricsTable({ metrics }: { metrics: Record<string, KindMetrics> }) {
  const kinds = Object.keys(metrics);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {kinds.map((kind) => (
              <th scope="col" key={kind} className={kind === "mandate" ? "ours" : undefined}>
                {KIND_NAMES[kind] ?? kind}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.label}>
              <th scope="row">
                {row.label}
                {row.better && <span className="muted small"> ({row.better})</span>}
              </th>
              {kinds.map((kind) => (
                <td key={kind} className={kind === "mandate" ? "ours" : undefined}>
                  {row.value(metrics[kind])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
