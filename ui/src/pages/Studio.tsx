// The rule studio: write what the owner wants in plain words and see, before saying it, the
// rules it makes, what it contradicts and which recent requests it would change; then try
// any action against the live rules without recording anything.

import type { Icon } from "../icons";
import { AlertTriangle, ArrowRight, Bot, CircleHelp, Clock, FlaskConical, GitBranch, ListTree, MessageSquareText, PenLine, Play, ScrollText, ShieldCheck, Sparkles, StickyNote, User, Wand2 } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorNote, ResultBadge } from "../components/Bits";
import { Card, CardHead, ease, EmptyState, PageHeader, Spinner } from "../components/ui";
import type { CheckOutcome, Preview, PreviewRule } from "../types";
import { useLoad } from "../useLoad";

export const EFFECT_WORD: Record<PreviewRule["effect"], string> = {
  allow: "Allow",
  confirm: "Ask first",
  deny: "Never",
};

export const ACTION_LABEL: Record<string, string> = {
  "email.read": "read email",
  "email.archive": "archive email",
  "email.delete": "delete email",
  "email.send": "send email",
  "refund.issue": "issue refunds",
  "file.read": "read files",
  "file.write": "write files",
  "file.delete": "delete files",
};

export const REASON_TEXT: Record<string, string> = {
  authorized: "a rule allows it",
  confirm_rule: "a rule says ask the owner first",
  mixed_lineage: "its authority is partly from untrusted content",
  explicit_deny: "a rule forbids it",
  authority_revoked: "the rule that allowed it was revoked",
  constraint_not_met: "it is over the rule's limit",
  no_authority_path: "no rule allows it",
  check_error: "the check could not finish",
};

const SAMPLE_RESOURCE: Record<string, string> = {
  "email.read": "inbox/m-1",
  "email.archive": "inbox/m-1",
  "email.delete": "inbox/m-1",
  "email.send": "outbox/reply-1",
  "refund.issue": "order/1042",
  "file.read": "files/report.txt",
  "file.write": "files/report.txt",
  "file.delete": "files/report.txt",
};

const EXAMPLES = [
  "You can read and archive my email, but ask me before deleting anything.",
  "For the next 2 hours, you may issue refunds up to $1,000.",
  "Never forward or reply to anything.",
  "You may read my files, but you must not trash them.",
];

const HOP_ICONS: Record<string, Icon> = {
  Principal: User,
  Utterance: MessageSquareText,
  Instruction: ScrollText,
  Delegation: GitBranch,
  Agent: Bot,
  Note: StickyNote,
};

export function duration(ms: number): string {
  const units: [number, string][] = [
    [604_800_000, "week"],
    [86_400_000, "day"],
    [3_600_000, "hour"],
    [60_000, "minute"],
  ];
  for (const [size, name] of units) {
    if (ms % size === 0) {
      const n = ms / size;
      return `${n} ${name}${n === 1 ? "" : "s"}`;
    }
  }
  return `${Math.round(ms / 60_000)} minutes`;
}

/** "issue refunds up to $500 on order/*" */
export function describeRule(rule: {
  action_type: string;
  resource_pattern: string;
  max_amount: number | null;
}): string {
  const action = ACTION_LABEL[rule.action_type] ?? rule.action_type;
  const limit = rule.max_amount != null ? ` up to $${rule.max_amount.toLocaleString()}` : "";
  const where = rule.resource_pattern === "*" ? "" : ` in ${rule.resource_pattern}`;
  return `${action}${limit}${where}`;
}

const CONFLICT_TEXT = {
  contradicts: "Contradicts",
  duplicates: "Repeats",
  changes_limit: "Changes the limit of",
} as const;

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

function PreviewPanel({ tid, preview }: { tid: string; preview: Preview }) {
  const flipped = preview.changes.filter((c) => c.result_changed);
  const reasonOnly = preview.changes.filter((c) => !c.result_changed);
  return (
    <div className="studio-preview">
      <section aria-label="Rules this would make">
        <h3 className="studio-h">
          <Wand2 size={15} aria-hidden="true" /> This would make {preview.rules.length} rule
          {preview.rules.length === 1 ? "" : "s"}
        </h3>
        {preview.rules.length === 0 && (
          <p className="muted small">
            Nothing here is a rule the studio can read, so nothing would change. Try one of the
            examples.
          </p>
        )}
        <ul className="rule-preview-list">
          <AnimatePresence initial={false}>
            {preview.rules.map((rule, index) => (
              <motion.li
                key={`${rule.effect}-${rule.action_type}-${index}`}
                className={`rule-preview effect-${rule.effect}`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.22, ease, delay: index * 0.04 }}
              >
                <span className={`effect-pill effect-${rule.effect}`}>{EFFECT_WORD[rule.effect]}</span>
                <span className="rule-preview-text">{describeRule(rule)}</span>
                <span className="chips">
                  {rule.valid_for_ms && (
                    <span className="chip chip-soft" title="The rule stops applying after this">
                      <Clock size={12} aria-hidden="true" /> for {duration(rule.valid_for_ms)}
                    </span>
                  )}
                  {rule.needs_confirmation && (
                    <span className="chip flag-warn" title="High impact: the owner confirms it">
                      needs confirmation
                    </span>
                  )}
                </span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </section>

      {preview.unparsed.length > 0 && (
        <div className="callout callout-warn" role="note">
          <CircleHelp size={16} aria-hidden="true" />
          <div>
            <strong>Not understood, so nothing is made from:</strong>
            <ul className="plain-list">
              {preview.unparsed.map((clause) => (
                <li key={clause}>“{clause}”</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {preview.conflicts.length > 0 && (
        <section aria-label="Conflicts">
          <h3 className="studio-h">
            <AlertTriangle size={15} aria-hidden="true" /> Overlaps with {preview.conflicts.length}{" "}
            live rule{preview.conflicts.length === 1 ? "" : "s"}
          </h3>
          <ul className="conflict-list">
            {preview.conflicts.map((c) => (
              <li key={`${c.rule}-${c.instruction_id}`} className={`conflict conflict-${c.kind}`}>
                <span className="conflict-kind">{CONFLICT_TEXT[c.kind]}</span>{" "}
                <Link to={`/tenants/${tid}/instructions/${c.instruction_id}`}>“{c.text_span}”</Link>{" "}
                <span className="muted small">
                  ({EFFECT_WORD[c.effect].toLowerCase()} {describeRule(c)})
                </span>
                <div className="muted small">
                  {c.kind === "contradicts"
                    ? "Where both apply, the newer rule wins: this one, once it is in effect."
                    : c.kind === "duplicates"
                      ? "Saying it again replaces the old rule with this one."
                      : "This one replaces the old limit."}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {preview.rules.length > 0 && (
        <section aria-label="What would change">
          <h3 className="studio-h">
            <FlaskConical size={15} aria-hidden="true" />
            {preview.evaluated === 0
              ? "No recent requests to re-check"
              : `Would change ${flipped.length} of ${preview.evaluated} recent request${preview.evaluated === 1 ? "" : "s"}`}
          </h3>
          <p className="muted small">
            Re-checked on a throwaway copy of this tenant's graph with the sentence said and
            confirmed. Nothing live was changed.
          </p>
          {preview.changes.length > 0 && (
            <div className="table-wrap">
              <table className="impact-table">
                <thead>
                  <tr>
                    <th scope="col">Request</th>
                    <th scope="col">Today</th>
                    <th scope="col">
                      <span className="sr-only">becomes</span>
                    </th>
                    <th scope="col">With this</th>
                  </tr>
                </thead>
                <tbody>
                  {[...flipped, ...reasonOnly].map((c, index) => (
                    <motion.tr
                      key={`${c.agent_id}-${c.action_type}-${c.resource}-${c.amount}`}
                      className={c.result_changed ? "lit" : "row-muted"}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.04 }}
                    >
                      <td>
                        <Link to={`/tenants/${tid}/decisions/${c.example_decision_id}`}>
                          {ACTION_LABEL[c.action_type] ?? c.action_type}
                        </Link>{" "}
                        <span className="mono small">{c.resource}</span>
                        {c.amount != null && <span className="small"> · ${c.amount}</span>}
                      </td>
                      <td>
                        <ResultBadge result={c.was_result} />
                        <div className="muted small">{REASON_TEXT[c.was_reason] ?? c.was_reason}</div>
                      </td>
                      <td aria-hidden="true">
                        <ArrowRight size={14} className="muted" />
                      </td>
                      <td>
                        <ResultBadge result={c.now_result} />
                        <div className="muted small">{REASON_TEXT[c.now_reason] ?? c.now_reason}</div>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function Composer({ tid, ownerId, agentIds }: { tid: string; ownerId: string; agentIds: string[] }) {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const settled = useDebounced(text.trim(), 550);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState<null | "pending" | "confirm">(null);
  const admin = can("admin");

  useEffect(() => {
    if (!settled || !can("operator")) {
      setPreview(null);
      return;
    }
    let live = true;
    setPreviewing(true);
    api
      .preview(tid, ownerId, settled, agentIds.length ? agentIds : undefined)
      .then((result) => {
        if (!live) return;
        setPreview(result);
        setError(null);
      })
      .catch((reason: unknown) => live && setError(reason))
      .finally(() => live && setPreviewing(false));
    return () => {
      live = false;
    };
  }, [settled, tid, ownerId, agentIds, can]);

  async function save(confirm: boolean, event?: FormEvent) {
    event?.preventDefault();
    setSaving(confirm ? "confirm" : "pending");
    setError(null);
    try {
      const said = await api.say(tid, ownerId, text.trim(), agentIds.length ? agentIds : undefined);
      const waiting = said.instructions.filter((i) => i.needs_confirmation);
      if (confirm) {
        for (const item of waiting) await api.confirm(tid, item.instruction.id, ownerId);
      }
      const made = said.instructions.length;
      const pending = confirm ? 0 : waiting.length;
      toast.success(
        made === 0
          ? "Recorded. Nothing in it was a rule."
          : `${made} rule${made === 1 ? "" : "s"} recorded${pending ? `; ${pending} waiting for confirmation` : ", in effect now"}.`,
        { action: { label: "View rules", onClick: () => navigate(`/tenants/${tid}?tab=rules`) } },
      );
      setText("");
      setPreview(null);
    } catch (reason) {
      setError(reason);
    } finally {
      setSaving(null);
    }
  }

  const needsConfirmation = preview?.rules.some((r) => r.needs_confirmation) ?? false;
  const stale = text.trim() !== settled;

  return (
    <Card>
      <CardHead
        icon={PenLine}
        title="Say a rule"
        hint="in the owner's words"
        right={
          (previewing || stale) && text.trim() ? (
            <span className="muted small studio-status" aria-live="polite">
              <Spinner /> previewing on a copy of the graph…
            </span>
          ) : null
        }
      />
      <form className="card-body studio-form" onSubmit={(e) => void save(true, e)}>
        <label className="sr-only" htmlFor="studio-text">
          What the owner says
        </label>
        <textarea
          id="studio-text"
          className="studio-text"
          rows={3}
          maxLength={4000}
          placeholder="You may issue refunds up to $500, but ask me before sending anything."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="studio-examples" role="group" aria-label="Examples">
          <Sparkles size={14} aria-hidden="true" className="muted" />
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="example-chip unstyled"
              onClick={() => setText(example)}
            >
              {example}
            </button>
          ))}
        </div>
        <ErrorNote error={error} />
        {!can("operator") && (
          <p className="callout callout-info small">Previewing needs the operator role or above.</p>
        )}
        <AnimatePresence mode="wait">
          {preview && settled && (
            <motion.div
              key="preview"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: stale ? 0.55 : 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <PreviewPanel tid={tid} preview={preview} />
            </motion.div>
          )}
        </AnimatePresence>
        <div className="studio-actions">
          {needsConfirmation && (
            <button
              type="button"
              onClick={() => void save(false)}
              disabled={!admin || !text.trim() || saving !== null}
              title={admin ? "Record it; the high-impact rules wait for confirmation" : "Needs the admin role"}
            >
              {saving === "pending" && <Spinner />} Save, confirm later
            </button>
          )}
          <button
            type="submit"
            className="primary"
            disabled={!admin || !text.trim() || saving !== null || !preview?.rules.length}
            title={admin ? undefined : "Saying rules needs the admin role"}
          >
            {saving === "confirm" ? <Spinner /> : <ShieldCheck size={15} aria-hidden="true" />}
            {needsConfirmation ? "Save and confirm as the owner" : "Save rule"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function Simulator({
  tid,
  agents,
}: {
  tid: string;
  agents: { id: string; name: string; kind: string }[];
}) {
  const { can } = useAuth();
  const [agentId, setAgentId] = useState("");
  const [action, setAction] = useState("refund.issue");
  const [resource, setResource] = useState(SAMPLE_RESOURCE["refund.issue"]);
  const [amount, setAmount] = useState("250");
  const [outcome, setOutcome] = useState<CheckOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const chosen = agentId || agents[0]?.id || "";

  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const args: Record<string, unknown> = action === "refund.issue" ? { amount: Number(amount) } : {};
      setOutcome(await api.simulate(tid, { agent_id: chosen, action_type: action, resource, args }));
    } catch (reason) {
      setError(reason);
      setOutcome(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card delay={0.05}>
      <CardHead icon={FlaskConical} title="Try an action" hint="decided now, never recorded" />
      <form className="card-body sim-form" onSubmit={(e) => void run(e)}>
        <label className="field">
          <span>Agent</span>
          <select value={chosen} onChange={(e) => setAgentId(e.target.value)}>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.kind})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Action</span>
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setResource(SAMPLE_RESOURCE[e.target.value] ?? "");
              setOutcome(null);
            }}
          >
            {Object.entries(ACTION_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label} ({value})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>On</span>
          <input type="text" className="mono" value={resource} onChange={(e) => setResource(e.target.value)} />
        </label>
        {action === "refund.issue" && (
          <label className="field">
            <span>Amount ($)</span>
            <input
              type="number"
              min={0}
              inputMode="numeric"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
        )}
        <button
          type="submit"
          className="primary"
          disabled={busy || !chosen || !resource.trim() || !can("operator")}
          title={can("operator") ? undefined : "Needs the operator role or above"}
        >
          {busy ? <Spinner /> : <Play size={15} aria-hidden="true" />} Check
        </button>
      </form>
      <ErrorNote error={error} />
      <AnimatePresence mode="wait">
        {outcome && (
          <motion.div
            key={`${outcome.result}-${outcome.reason}-${outcome.latency_ms}`}
            className={`sim-outcome result-${outcome.result}`}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease }}
            role="status"
          >
            <div className="sim-verdict">
              <ResultBadge result={outcome.result} />
              <span>
                because {REASON_TEXT[outcome.reason] ?? outcome.reason.replaceAll("_", " ")}
              </span>
              <span className="muted small sim-latency">{outcome.latency_ms.toFixed(1)} ms</span>
            </div>
            {outcome.path.length > 0 && (
              <>
                <h4 className="studio-h">
                  <ListTree size={14} aria-hidden="true" /> The chain
                </h4>
                <ol className="path compact">
                  {outcome.path.map((hop, index) => {
                    const Icon = HOP_ICONS[hop.type] ?? StickyNote;
                    return (
                      <motion.li
                        key={`${hop.id}-${index}`}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.05 + index * 0.05 }}
                      >
                        <span className="hop-dot" aria-hidden="true">
                          <Icon size={14} />
                        </span>
                        <span className="hop-type">{hop.type}</span>{" "}
                        {hop.type === "Instruction" ? (
                          <Link className="mono" to={`/tenants/${tid}/instructions/${hop.id}`}>
                            {hop.id}
                          </Link>
                        ) : (
                          <span className="mono muted">{hop.type === "Note" ? "" : hop.id}</span>
                        )}
                        {hop.note && <span className="muted small"> {hop.note}</span>}
                      </motion.li>
                    );
                  })}
                </ol>
              </>
            )}
            <p className="muted small" style={{ margin: "10px 0 0" }}>
              A dry run: no decision or action was recorded, and no agent was told.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

export function Studio() {
  const { tid = "" } = useParams();
  const principals = useLoad(() => api.principals(tid), [tid]);
  const agents = useLoad(() => api.agents(tid), [tid]);
  const owner = principals.data?.find((p) => p.role === "owner");
  const allAgents = agents.data ?? [];
  const [targets, setTargets] = useState<string[]>([]);
  const targetKey = useMemo(() => [...targets].sort(), [targets]);

  const toggle = (id: string) =>
    setTargets((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <Wand2 size={14} aria-hidden="true" /> Rule studio
          </>
        }
        title={
          <>
            Rules for <span className="mono">{tid}</span>
          </>
        }
        description="Write a rule the way the owner would say it. Before anything is saved you see the rules it makes, what it overlaps, and which recent requests it would decide differently. Then try any action against the live rules."
      />
      <ErrorNote error={principals.error ?? agents.error} />
      {principals.data && !owner && (
        <EmptyState icon={User} title="This tenant has no owner">
          Rules come only from an owner's words. Add an owner principal first.
        </EmptyState>
      )}
      {owner && agents.data && (
        <>
          <div className="studio-targets" role="group" aria-label="Agents the rule applies to">
            <span className="muted small">Applies to</span>
            {allAgents.map((a) => {
              const on = targets.includes(a.id) || (targets.length === 0 && a.kind === "primary");
              return (
                <button
                  key={a.id}
                  type="button"
                  className={`target-chip unstyled${on ? " on" : ""}`}
                  aria-pressed={on}
                  onClick={() => toggle(a.id)}
                >
                  <Bot size={13} aria-hidden="true" /> {a.name}
                  <span className="muted small"> {a.kind}</span>
                </button>
              );
            })}
            {targets.length === 0 && <span className="muted small">(primary agents by default)</span>}
          </div>
          <div className="studio-grid">
            <Composer tid={tid} ownerId={owner.id} agentIds={targetKey} />
            <Simulator tid={tid} agents={allAgents} />
          </div>
        </>
      )}
    </div>
  );
}

