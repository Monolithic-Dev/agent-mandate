// The tenants: the seeded demo and any scenario runs, as a searchable grid of cards.

import { Building2, Clock, FlaskConical, Search } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ErrorNote, relativeTime, shortTime } from "../components/Bits";
import { EmptyState, PageHeader } from "../components/ui";
import { useLoad } from "../useLoad";

const HUES = [238, 262, 199, 160, 330, 24, 280];

function hue(id: string): number {
  let sum = 0;
  for (const char of id) sum = (sum * 31 + char.charCodeAt(0)) % 997;
  return HUES[sum % HUES.length];
}

export function Tenants() {
  const tenants = useLoad(() => api.tenants(), []);
  const [query, setQuery] = useState("");
  const sorted = [...(tenants.data ?? [])].sort((a, b) => b.created_at - a.created_at);
  const shown = sorted.filter((t) =>
    `${t.tenant_id} ${t.name}`.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <Building2 size={14} aria-hidden="true" /> Workspace
          </>
        }
        title="Tenants"
        description={
          <>
            Each tenant is its own graph. <code>demo</code> is the seeded story; <code>run_…</code>{" "}
            tenants hold scenario runs from the demo page.
          </>
        }
        actions={
          <label className="field" style={{ minWidth: 260 }}>
            <span className="sr-only">Filter tenants</span>
            <span style={{ position: "relative", display: "block" }}>
              <Search
                size={15}
                aria-hidden="true"
                className="muted"
                style={{ position: "absolute", left: 10, top: 10 }}
              />
              <input
                type="search"
                placeholder="Filter tenants…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{ paddingLeft: 32, width: "100%" }}
              />
            </span>
          </label>
        }
      />
      <ErrorNote error={tenants.error} />
      {tenants.loading && !tenants.data && (
        <div className="grid-cards" aria-busy="true">
          <span className="sr-only">Loading tenants…</span>
          {[0, 1, 2].map((i) => (
            <div key={i} className="card skeleton" style={{ height: 112 }} />
          ))}
        </div>
      )}
      {tenants.data && sorted.length === 0 && (
        <EmptyState icon={Building2} title="No tenants yet">
          Reset the demo tenant or run a scenario on the demo page.
        </EmptyState>
      )}
      {tenants.data && sorted.length > 0 && shown.length === 0 && (
        <EmptyState icon={Search} title="No tenant matches that filter" />
      )}
      <ul className="grid-cards" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        <AnimatePresence initial={false}>
          {shown.map((t, index) => {
            const isRun = t.tenant_id.startsWith("run_");
            return (
              <motion.li
                key={t.tenant_id}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.25, delay: Math.min(index, 12) * 0.03 }}
              >
                <Link to={`/tenants/${t.tenant_id}`} className="card tenant-card">
                  <div className="row">
                    <span
                      className="avatar"
                      aria-hidden="true"
                      style={{
                        background: `linear-gradient(135deg, hsl(${hue(t.tenant_id)} 70% 58%), hsl(${hue(t.tenant_id) + 30} 70% 48%))`,
                      }}
                    >
                      {t.tenant_id.replace(/^run_/, "").slice(0, 2).toUpperCase()}
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, color: "var(--text)" }} className="mono">
                        {t.tenant_id}
                      </div>
                      <div className="muted small">{t.name}</div>
                    </div>
                  </div>
                  <div className="tenant-meta">
                    <span title={shortTime(t.created_at)}>
                      <Clock size={12} aria-hidden="true" /> created {relativeTime(t.created_at)}
                    </span>
                    {isRun && (
                      <span>
                        <FlaskConical size={12} aria-hidden="true" /> scenario run
                      </span>
                    )}
                  </div>
                </Link>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </div>
  );
}
