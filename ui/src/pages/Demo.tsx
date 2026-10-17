// Flow A: pick a scenario, run it for a baseline and Agent Mandate, watch it side by side.

import { ArrowRight, FastForward, Play, RotateCcw, Sparkles } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorNote } from "../components/Bits";
import { KIND_NAMES, SplitRun } from "../components/SplitRun";
import { ease, Spinner } from "../components/ui";
import type { Run, SeedResult } from "../types";
import { useLoad } from "../useLoad";

const STEP_MS = 650;
const BASELINES = ["naive", "flat", "static"] as const;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

export function Demo() {
  const { can } = useAuth();
  const admin = can("admin");
  const needsAdmin = admin ? undefined : "Running scenarios needs the admin role";
  const scenarios = useLoad(() => api.scenarios(), []);
  const [scenarioId, setScenarioId] = useState("S1_rule_lost_v1");
  const [baseline, setBaseline] = useState<string>("naive");
  const [run, setRun] = useState<Run | null>(null);
  const [shown, setShown] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [seeded, setSeeded] = useState<SeedResult | null>(null);
  const [resetting, setResetting] = useState(false);

  const total = run ? Math.max(...run.runs.map((r) => r.timeline.length)) : 0;
  const finished = run !== null && shown >= total;

  useEffect(() => {
    if (!run || shown >= total) return;
    const timer = window.setTimeout(() => setShown((n) => n + 1), STEP_MS);
    return () => window.clearTimeout(timer);
  }, [run, shown, total]);

  const families = useMemo(() => {
    const grouped = new Map<string, { id: string; description: string }[]>();
    for (const s of scenarios.data ?? []) {
      grouped.set(s.family, [...(grouped.get(s.family) ?? []), s]);
    }
    return [...grouped.entries()];
  }, [scenarios.data]);
  const selected = scenarios.data?.find((s) => s.id === scenarioId);

  async function start() {
    setRunning(true);
    setError(null);
    setRun(null);
    try {
      const result = await api.run(scenarioId, [baseline, "mandate"]);
      setRun(result);
      setShown(prefersReducedMotion() ? Number.MAX_SAFE_INTEGER : 1);
    } catch (reason) {
      setError(reason);
    } finally {
      setRunning(false);
    }
  }

  async function resetDemo() {
    setResetting(true);
    setError(null);
    try {
      const result = await api.resetDemo();
      setSeeded(result);
      toast.success(`Demo tenant re-seeded with ${result.decision_ids.length} decisions`);
    } catch (reason) {
      setError(reason);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="page">
      <motion.section
        className="hero"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease }}
      >
        <div className="eyebrow" style={{ color: "var(--accent)" }}>
          <Sparkles size={14} aria-hidden="true" /> Live comparison
        </div>
        <h1>Agents keep your rules in memory. Memory gets summarised.</h1>
        <p className="lead">
          Run a scripted scenario for an ordinary agent and for Agent Mandate, side by side. The
          same script, the same tool calls; only the gate differs.
        </p>

        <form
          className="toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            void start();
          }}
        >
          <label className="field">
            Scenario
            <select
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              disabled={scenarios.loading && !scenarios.data}
            >
              {!scenarios.data && <option value={scenarioId}>Loading scenarios…</option>}
              {families.map(([family, items]) => (
                <optgroup key={family} label={family}>
                  {items.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.id}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="field">
            Compare with
            <select value={baseline} onChange={(e) => setBaseline(e.target.value)}>
              {BASELINES.map((kind) => (
                <option key={kind} value={kind}>
                  {KIND_NAMES[kind]}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="primary"
            disabled={running || !selected || !admin}
            title={needsAdmin}
          >
            {running ? <Spinner /> : <Play size={15} aria-hidden="true" />}
            {running ? "Running…" : "Run"}
          </button>
          {run && !finished && (
            <button type="button" onClick={() => setShown(Number.MAX_SAFE_INTEGER)}>
              <FastForward size={15} aria-hidden="true" /> Show all
            </button>
          )}
          {run && finished && (
            <button type="button" onClick={() => setShown(1)}>
              <RotateCcw size={15} aria-hidden="true" /> Replay
            </button>
          )}
          <span className="spacer" />
          <button
            type="button"
            className="ghost"
            onClick={() => void resetDemo()}
            disabled={resetting || !admin}
            title={needsAdmin}
          >
            {resetting ? <Spinner /> : <RotateCcw size={15} aria-hidden="true" />}
            {resetting ? "Resetting…" : "Reset demo tenant"}
          </button>
        </form>
        {selected && (
          <p className="muted small" style={{ marginTop: 12 }}>
            {selected.description}
          </p>
        )}
        {!admin && (
          <p className="callout callout-info small" style={{ marginTop: 12 }}>
            You are signed in with a read-only role: you can explore tenants, decisions and the
            graph, but running a scenario changes data and needs an admin.
          </p>
        )}
        {run && (
          <div className="progress" aria-hidden="true">
            <motion.div
              className="progress-bar"
              initial={false}
              animate={{ scaleX: total ? Math.min(shown, total) / total : 0 }}
              transition={{ duration: 0.4, ease }}
            />
          </div>
        )}
      </motion.section>

      <ErrorNote error={scenarios.error ?? error} />
      <AnimatePresence>
        {seeded && (
          <motion.div
            className="callout callout-good"
            role="status"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
          >
            <div>
              Demo tenant re-seeded with {seeded.decision_ids.length} decisions.{" "}
              <Link to={`/tenants/${seeded.tenant_id}`}>Open it</Link> or{" "}
              <Link to={`/tenants/${seeded.tenant_id}/instructions/${seeded.typo_rule_id}`}>
                the mistaken refund rule
              </Link>
              .
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {running && !run && (
        <div className="split">
          {[0, 1].map((i) => (
            <div key={i} className="card skeleton" style={{ height: 320 }} />
          ))}
        </div>
      )}
      {run && <SplitRun run={run} shown={Math.min(shown, total)} />}
      {run && finished && run.tenant_id && (
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ marginTop: 18 }}>
          <Link
            to={`/tenants/${run.tenant_id}`}
            style={{ display: "inline-flex", gap: 6, alignItems: "center", fontWeight: 500 }}
          >
            Explore this run's graph and decisions <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </motion.p>
      )}
    </div>
  );
}
