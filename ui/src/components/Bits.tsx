// Small shared pieces: errors, loading, result badges and attempt status chips.
// Every state has an icon and a word, so colour is never the only signal.

import type { Icon } from "../icons";
import { Ban, CheckCircle2, CircleAlert, CirclePause, CircleX, PlayCircle } from "../icons";
import { motion } from "motion/react";
import type { ReactNode } from "react";

import { ApiError } from "../api";
import type { AttemptStatus, Result } from "../types";

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <motion.div
      className="error"
      role="alert"
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <CircleAlert size={16} aria-hidden="true" color="var(--deny)" />
      <div>
        <strong>Something went wrong:</strong> {message}
        {api && (
          <span className="muted small">
            {" "}
            ({api.code}
            {api.requestId ? `, request ${api.requestId}` : ""})
          </span>
        )}
      </div>
    </motion.div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p className="muted" aria-busy="true" style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <span className="skeleton" style={{ width: 14, height: 14, borderRadius: 4 }} />
      {what}…
    </p>
  );
}

const RESULT: Record<Result, { icon: Icon; word: string }> = {
  allow: { icon: CheckCircle2, word: "Allowed" },
  confirm: { icon: CirclePause, word: "Needs approval" },
  deny: { icon: CircleX, word: "Denied" },
};

export function ResultBadge({ result }: { result: Result }) {
  const { icon: Icon, word } = RESULT[result];
  return (
    <span className={`badge result-${result}`}>
      <Icon size={13} aria-hidden="true" /> {word}
    </span>
  );
}

const STATUS: Record<AttemptStatus, { icon: Icon; word: string }> = {
  executed: { icon: PlayCircle, word: "EXECUTED" },
  approved: { icon: CheckCircle2, word: "APPROVED" },
  held: { icon: CirclePause, word: "CONFIRM" },
  denied: { icon: Ban, word: "DENIED" },
};

export function StatusChip({
  status,
  unauthorised = false,
  falseBlock = false,
}: {
  status: AttemptStatus;
  unauthorised?: boolean;
  falseBlock?: boolean;
}) {
  const { icon: Icon, word } = STATUS[status];
  return (
    <span className="chips">
      <span className={`chip status-${status}`}>
        <Icon size={12} aria-hidden="true" /> {word}
      </span>
      {unauthorised && <span className="chip flag-bad">unauthorised</span>}
      {falseBlock && <span className="chip flag-warn">blocked a legitimate request</span>}
    </span>
  );
}

export function Chip({ kind, children }: { kind: string; children: ReactNode }) {
  return <span className={`chip ${kind}`}>{children}</span>;
}

export function shortTime(epochMs: number): string {
  return new Date(epochMs).toISOString().replace("T", " ").slice(0, 19);
}

/** "3 minutes ago"-style time for lists; the exact time is in the title attribute. */
export function relativeTime(epochMs: number, now = Date.now()): string {
  const seconds = Math.round((now - epochMs) / 1000);
  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [30, "day"],
    [12, "month"],
    [Number.POSITIVE_INFINITY, "year"],
  ];
  let value = -seconds;
  for (const [size, unit] of units) {
    if (Math.abs(value) < size) {
      return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(Math.round(value), unit);
    }
    value /= size;
  }
  return shortTime(epochMs);
}
