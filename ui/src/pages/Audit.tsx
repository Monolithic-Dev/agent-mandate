// The audit log: every change anyone made, through the console, an API key, an approval
// link or the server's command line, as a timeline in plain sentences. Admins only.

import type { Icon } from "../icons";
import { Ban, Building2, ChevronDown, Download, FileClock, Gavel, KeyRound, Link2, LogIn, RefreshCw, ScrollText, ShieldAlert, ShieldCheck, Terminal, UserCog, Users as UsersIcon, X } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorNote, relativeTime, shortTime } from "../components/Bits";
import {
  Card,
  EmptyState,
  PageHeader,
  SkeletonRows,
  Spinner,
  StatCard,
} from "../components/ui";
import type { AuditEvent, AuditFilter, Outcome, Tenant } from "../types";

type Category = "auth" | "rules" | "approvals" | "admin" | "tenants" | "tokens" | "other";

interface ActionText {
  verb: string;
  category: Category;
}

// What each action says in a sentence: "<actor> <verb> [in <tenant>]".
export const ACTION_TEXT: Record<string, ActionText> = {
  "auth.login": { verb: "signed in", category: "auth" },
  "auth.logout": { verb: "signed out", category: "auth" },
  "auth.password_change": { verb: "changed their password", category: "auth" },
  "auth.sessions_end": { verb: "signed out everywhere", category: "auth" },
  "owner.say": { verb: "recorded what the owner said", category: "rules" },
  "rule.confirm": { verb: "confirmed a rule", category: "rules" },
  "rule.revoke": { verb: "revoked a rule", category: "rules" },
  "rule.quarantine": { verb: "quarantined a rule", category: "rules" },
  "rule.release": { verb: "released a rule from quarantine", category: "rules" },
  "rule.replay": { verb: "replayed decisions without a rule", category: "rules" },
  "delegation.create": { verb: "delegated authority between agents", category: "rules" },
  "delegation.revoke": { verb: "revoked a delegation", category: "rules" },
  "action.resolve": { verb: "decided on a held action", category: "approvals" },
  "action.resolve_by_link": { verb: "decided on a held action with a link", category: "approvals" },
  "approval_link.create": { verb: "made an approval link", category: "approvals" },
  "token.mint": { verb: "issued an agent token", category: "tokens" },
  "token.revoke": { verb: "revoked an agent token", category: "tokens" },
  "tenant.create": { verb: "created a tenant", category: "tenants" },
  "tenant.delete": { verb: "deleted a tenant", category: "tenants" },
  "principal.create": { verb: "added a principal", category: "tenants" },
  "agent.create": { verb: "registered an agent", category: "tenants" },
  "scenario.run": { verb: "ran a scenario", category: "tenants" },
  "demo.reset": { verb: "re-seeded the demo tenant", category: "tenants" },
  "user.create": { verb: "created a user", category: "admin" },
  "user.update": { verb: "changed a user", category: "admin" },
  "user.password_reset": { verb: "reset a user's password", category: "admin" },
  "user.sessions_end": { verb: "signed a user out everywhere", category: "admin" },
};

const CATEGORY: Record<Category, { label: string; icon: Icon }> = {
  auth: { label: "Sign-ins", icon: LogIn },
  rules: { label: "Rules", icon: ScrollText },
  approvals: { label: "Approvals", icon: Gavel },
  admin: { label: "Users", icon: UserCog },
  tenants: { label: "Tenants and agents", icon: Building2 },
  tokens: { label: "Agent tokens", icon: KeyRound },
  other: { label: "Other", icon: FileClock },
};

const ACTOR_ICON: Record<AuditEvent["actor_kind"], Icon> = {
  user: UsersIcon,
  key: KeyRound,
  link: Link2,
  cli: Terminal,
  anonymous: ShieldAlert,
};

const OUTCOMES: { value: Outcome | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "success", label: "Succeeded" },
  { value: "denied", label: "Denied" },
  { value: "failed", label: "Failed" },
];

const INFINITIVE: Record<string, string> = {
  signed: "sign",
  changed: "change",
  recorded: "record",
  confirmed: "confirm",
  revoked: "revoke",
  quarantined: "quarantine",
  released: "release",
  replayed: "replay",
  delegated: "delegate",
  decided: "decide",
  made: "make",
  issued: "issue",
  created: "create",
  deleted: "delete",
  added: "add",
  registered: "register",
  ran: "run",
  "re-seeded": "re-seed",
  reset: "reset",
};

/** "confirmed a rule" -> "tried to confirm a rule", for a refused or failed attempt. */
function attempted(verb: string): string {
  const [first, ...rest] = verb.split(" ");
  return ["tried to", INFINITIVE[first] ?? first, ...rest].join(" ");
}

export function describe(event: AuditEvent): { actor: string; verb: string; category: Category } {
  const text = ACTION_TEXT[event.action];
  const actor =
    event.actor_kind === "anonymous"
      ? `Someone using ${event.actor_name ?? "an unknown email"}`
      : (event.actor_name ?? event.actor_id ?? "Someone");
  if (!text) return { actor, verb: `called ${event.method} ${event.route}`, category: "other" };
  if (event.outcome === "success") return { actor, verb: text.verb, category: text.category };
  const verb = event.action === "auth.login" ? "failed to sign in" : attempted(text.verb);
  return { actor, verb, category: text.category };
}

function dayLabel(at: number, now = new Date()): string {
  const day = new Date(at);
  const start = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((start(now) - start(day)) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return day.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

function targetLink(event: AuditEvent): string | null {
  if (!event.tenant_id || !event.target) return null;
  if (event.target.startsWith("ins_")) return `/tenants/${event.tenant_id}/instructions/${event.target}`;
  if (event.target.startsWith("dec_")) return `/tenants/${event.tenant_id}/decisions/${event.target}`;
  return null;
}

function EventRow({
  event,
  fresh,
  onActor,
}: {
  event: AuditEvent;
  fresh: boolean;
  onActor: (id: string, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const { actor, verb, category } = describe(event);
  const Icon = event.outcome === "success" ? CATEGORY[category].icon : Ban;
  const ActorIcon = ACTOR_ICON[event.actor_kind];
  const link = targetLink(event);
  const detailId = `audit-${event.id}`;
  return (
    <motion.li
      layout="position"
      className={`audit-item outcome-${event.outcome}${fresh ? " fresh" : ""}`}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <span className={`audit-icon cat-${category}`} aria-hidden="true">
        <Icon size={15} />
      </span>
      <div className="audit-body">
        <button
          type="button"
          className="audit-line unstyled"
          aria-expanded={open}
          aria-controls={detailId}
          onClick={() => setOpen((o) => !o)}
        >
          <span className="audit-sentence">
            <strong>{actor}</strong> {verb}
            {event.tenant_id && (
              <>
                {" "}
                in <span className="mono">{event.tenant_id}</span>
              </>
            )}
          </span>
          {event.outcome !== "success" && (
            <span className={`badge outcome-badge ${event.outcome}`}>
              {event.outcome === "denied" ? "Denied" : "Failed"} · {event.status}
            </span>
          )}
          <span className="audit-time muted small" title={shortTime(event.at)}>
            {relativeTime(event.at)}
          </span>
          <ChevronDown size={15} aria-hidden="true" className={`chev${open ? " open" : ""}`} />
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              id={detailId}
              className="audit-details"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <dl>
                <dt>Who</dt>
                <dd>
                  <ActorIcon size={13} aria-hidden="true" /> {event.actor_kind}
                  {event.actor_id && (
                    <>
                      {" · "}
                      <button
                        type="button"
                        className="linkish unstyled mono"
                        onClick={() => onActor(event.actor_id ?? "", actor)}
                        title="Show only this actor's events"
                      >
                        {event.actor_id}
                      </button>
                    </>
                  )}
                </dd>
                <dt>Action</dt>
                <dd className="mono">{event.action}</dd>
                <dt>Request</dt>
                <dd className="mono">
                  {event.method} {event.route} → {event.status || "—"}
                </dd>
                {event.target && (
                  <>
                    <dt>About</dt>
                    <dd className="mono">{link ? <Link to={link}>{event.target}</Link> : event.target}</dd>
                  </>
                )}
                <dt>When</dt>
                <dd>{new Date(event.at).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC")}</dd>
                {event.request_id && (
                  <>
                    <dt>Request id</dt>
                    <dd className="mono">{event.request_id}</dd>
                  </>
                )}
              </dl>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.li>
  );
}

export function Audit() {
  const { can } = useAuth();
  const [filter, setFilter] = useState<AuditFilter>({});
  const [actorName, setActorName] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | "all">("all");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [tick, setTick] = useState(0);
  const [tenants, setTenants] = useState<Tenant[]>([]);

  useEffect(() => {
    api.tenants().then(setTenants, () => setTenants([]));
  }, []);

  useEffect(() => {
    if (!can("admin")) return;
    let live = true;
    setLoading(true);
    api
      .audit(filter)
      .then((page) => {
        if (!live) return;
        setEvents((previous) => {
          const known = new Set(previous.map((e) => e.id));
          setFresh(previous.length ? new Set(page.events.filter((e) => !known.has(e.id)).map((e) => e.id)) : new Set());
          return page.events;
        });
        setNext(page.next);
        setError(null);
      })
      .catch((reason: unknown) => live && setError(reason))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [filter, tick, can]);

  const loadOlder = async () => {
    if (!next) return;
    setMore(true);
    try {
      const page = await api.audit(filter, next);
      setEvents((current) => [...current, ...page.events]);
      setNext(page.next);
    } catch (reason) {
      setError(reason);
    } finally {
      setMore(false);
    }
  };

  const shown = outcome === "all" ? events : events.filter((e) => e.outcome === outcome);
  const groups = useMemo(() => {
    const byDay = new Map<string, AuditEvent[]>();
    for (const event of shown) {
      const label = dayLabel(event.at);
      byDay.set(label, [...(byDay.get(label) ?? []), event]);
    }
    return [...byDay.entries()];
  }, [shown]);

  if (!can("admin")) {
    return (
      <div className="page">
        <PageHeader title="Audit log" />
        <EmptyState icon={ShieldAlert} title="The audit log is for admins.">
          Ask an administrator if you need to see who changed what.
        </EmptyState>
      </div>
    );
  }

  const set = (patch: AuditFilter) => setFilter((current) => {
    const merged = { ...current, ...patch };
    for (const key of Object.keys(merged) as (keyof AuditFilter)[]) {
      if (!merged[key]) delete merged[key];
    }
    return merged;
  });

  const denied = events.filter((e) => e.outcome === "denied").length;
  const actors = new Set(events.map((e) => e.actor_id ?? e.actor_name)).size;
  const signIns = events.filter((e) => e.action === "auth.login" && e.outcome === "success").length;

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <ShieldCheck size={14} aria-hidden="true" /> Administration
          </>
        }
        title="Audit log"
        description="Every change made through the console, an API key, an approval link or the server's command line, refusals included. Agents' own tool calls are in each tenant's decision log."
        actions={
          <>
            <button type="button" onClick={() => setTick((n) => n + 1)} disabled={loading}>
              {loading ? <Spinner /> : <RefreshCw size={15} aria-hidden="true" />} Refresh
            </button>
            <a className="btn" href={api.auditExportUrl(filter)} download>
              <Download size={15} aria-hidden="true" /> Export CSV
            </a>
          </>
        }
      />

      <div className="stats" style={{ marginBottom: 18 }}>
        <StatCard icon={FileClock} label="Events shown" value={events.length} tone="accent" sub={next ? "older events available" : "all matching events"} />
        <StatCard icon={Ban} label="Denied" value={denied} tone={denied > 0 ? "bad" : "neutral"} sub="refused requests and sign-ins" delay={0.04} />
        <StatCard icon={UsersIcon} label="Actors" value={actors} delay={0.08} />
        <StatCard icon={LogIn} label="Sign-ins" value={signIns} tone="good" delay={0.12} />
      </div>

      <div className="filter-bar" role="group" aria-label="Filter the audit log">
        <label className="field compact">
          <span>Tenant</span>
          <select value={filter.tenant_id ?? ""} onChange={(e) => set({ tenant_id: e.target.value || undefined })}>
            <option value="">All tenants</option>
            {tenants.map((t) => (
              <option key={t.tenant_id} value={t.tenant_id}>
                {t.tenant_id}
              </option>
            ))}
          </select>
        </label>
        <label className="field compact">
          <span>Activity</span>
          <select value={filter.action ?? ""} onChange={(e) => set({ action: e.target.value || undefined })}>
            <option value="">Everything</option>
            {(Object.keys(CATEGORY) as Category[])
              .filter((c) => c !== "other")
              .map((category) => (
                <optgroup key={category} label={CATEGORY[category].label}>
                  {Object.entries(ACTION_TEXT)
                    .filter(([, text]) => text.category === category)
                    .map(([action, text]) => (
                      <option key={action} value={action}>
                        {text.verb[0].toUpperCase() + text.verb.slice(1)}
                      </option>
                    ))}
                </optgroup>
              ))}
          </select>
        </label>
        <div className="segmented" role="radiogroup" aria-label="Outcome">
          {OUTCOMES.map((o) => (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={outcome === o.value}
              className={outcome === o.value ? "on" : undefined}
              onClick={() => setOutcome(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        {filter.actor_id && (
          <span className="chip chip-soft filter-chip">
            Actor: {actorName ?? filter.actor_id}
            <button
              type="button"
              className="unstyled"
              aria-label="Show every actor"
              onClick={() => {
                setActorName(null);
                set({ actor_id: undefined });
              }}
            >
              <X size={13} />
            </button>
          </span>
        )}
      </div>

      <Card className="card-flush">
        <ErrorNote error={error} />
        {loading && events.length === 0 && <SkeletonRows rows={6} label="Loading the audit log" />}
        {!loading && shown.length === 0 && (
          <EmptyState icon={FileClock} title="Nothing recorded here yet">
            Changes appear the moment they happen: sign-ins, rules, approvals, users.
          </EmptyState>
        )}
        {groups.map(([day, rows]) => (
          <section key={day} className="audit-day" aria-label={day}>
            <h3 className="audit-day-label">{day}</h3>
            <ol className="audit-list">
              {rows.map((event) => (
                <EventRow
                  key={event.id}
                  event={event}
                  fresh={fresh.has(event.id)}
                  onActor={(id, name) => {
                    setActorName(name);
                    set({ actor_id: id });
                  }}
                />
              ))}
            </ol>
          </section>
        ))}
        {next && (
          <div className="load-more">
            <button type="button" onClick={() => void loadOlder()} disabled={more}>
              {more && <Spinner />} Load older events
            </button>
          </div>
        )}
      </Card>
    </div>
  );
}
