// One scenario played by several agent kinds, side by side, revealed event by event.
// Each panel keeps its own score of unauthorised actions; the scoreboard repeats them
// (docs/ux-flows.md, flow A).

import type { Icon } from "../icons";
import { ArrowRightLeft, Bot, Brain, CircleHelp, Mail, MessageSquareText, Minimize2, ScanSearch, ShieldCheck, ShieldOff, XOctagon } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { Link } from "react-router-dom";

import type { KindRun, Run, TimelineEntry } from "../types";
import { StatusChip } from "./Bits";
import { ease, Pop } from "./ui";

export const KIND_NAMES: Record<string, string> = {
  naive: "Naive agent",
  flat: "Flat rules",
  static: "Static policy",
  mandate: "Agent Mandate",
};

const EVENT_ICONS: Record<string, Icon> = {
  owner_say: MessageSquareText,
  external_content: Mail,
  launder: Brain,
  compact: Minimize2,
  delegate: ArrowRightLeft,
  revoke_delegation: XOctagon,
  revoke_rule: XOctagon,
  agent_attempt: Bot,
  decide: CircleHelp,
  lineage_probe: ScanSearch,
};

function Entry({ entry, tenantId }: { entry: TimelineEntry; tenantId: string | null }) {
  const Icon = EVENT_ICONS[entry.event] ?? Bot;
  const decision =
    entry.decision_id && tenantId ? (
      <Link to={`/tenants/${tenantId}/decisions/${entry.decision_id}`}>why?</Link>
    ) : null;
  return (
    <motion.li
      className={`event event-${entry.event}`}
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.28, ease }}
      layout="position"
    >
      <span className="event-icon" aria-hidden="true">
        <Icon size={14} />
      </span>
      <div className="event-body">
        <div className="event-text">{entry.text}</div>
        {entry.status && (
          <div className="event-outcome">
            <StatusChip
              status={entry.status}
              unauthorised={entry.unauthorised}
              falseBlock={entry.false_block}
            />
            {entry.reason && <span className="muted"> {entry.reason.replaceAll("_", " ")}</span>}{" "}
            {decision}
          </div>
        )}
      </div>
    </motion.li>
  );
}

export function countUnauthorised(run: KindRun, shown: number): number {
  return run.timeline.slice(0, shown).filter((e) => e.unauthorised).length;
}

export function SplitRun({ run, shown }: { run: Run; shown: number }) {
  const total = Math.max(...run.runs.map((r) => r.timeline.length));
  const latest = run.runs
    .map((r) => (shown > 0 ? r.timeline[Math.min(shown, r.timeline.length) - 1] : undefined))
    .find((e) => e !== undefined);
  return (
    <section aria-label="Scenario run">
      <div className="split">
        {run.runs.map((kindRun, index) => {
          const ours = kindRun.kind === "mandate";
          const Mark = ours ? ShieldCheck : ShieldOff;
          return (
            <motion.div
              key={kindRun.kind}
              className={`card panel panel-${kindRun.kind}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease, delay: index * 0.06 }}
            >
              <div className="panel-head">
                <span className="panel-mark" aria-hidden="true">
                  <Mark size={16} />
                </span>
                <div>
                  <h3>{KIND_NAMES[kindRun.kind] ?? kindRun.kind}</h3>
                  <span className="muted small">
                    {ours ? "Every call checked against the graph" : "Rules kept in the prompt"}
                  </span>
                </div>
                <div className="panel-score" aria-hidden="true">
                  <strong>
                    <Pop value={countUnauthorised(kindRun, shown)} />
                  </strong>
                  <span>unauthorised</span>
                </div>
              </div>
              <ol className="timeline">
                <AnimatePresence initial={false}>
                  {kindRun.timeline.slice(0, shown).map((entry) => (
                    <Entry key={entry.seq} entry={entry} tenantId={ours ? run.tenant_id : null} />
                  ))}
                </AnimatePresence>
              </ol>
            </motion.div>
          );
        })}
      </div>
      <p className="sr-only" aria-live="polite">
        {latest ? `Event ${Math.min(shown, total)} of ${total}: ${latest.text}` : ""}
      </p>
      <footer className="scoreboard" aria-label="Unauthorised actions so far">
        <span className="scoreboard-title">Unauthorised actions</span>
        {run.runs.map((kindRun) => (
          <span
            key={kindRun.kind}
            className={`score ${kindRun.kind === "mandate" ? "score-mandate" : "score-bad"}`}
          >
            {KIND_NAMES[kindRun.kind] ?? kindRun.kind}{" "}
            <strong data-testid={`count-${kindRun.kind}`}>
              {countUnauthorised(kindRun, shown)}
            </strong>
          </span>
        ))}
        <span className="spacer" />
        <span className="muted small">
          {Math.min(shown, total)} of {total} events
        </span>
      </footer>
    </section>
  );
}
