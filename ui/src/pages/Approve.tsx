// An approval link opened by the owner: the action, why it is held, approve or decline.
// The token is in the URL fragment, which browsers never send to a server, and goes to the
// API in a request body. The link is the credential; no API key is involved. This page
// stands alone, without the console around it: the owner is not an operator.

import { BrandMark } from "../components/BrandMark";
import { Bot, Check, CircleCheck, CircleSlash, Clock, ShieldCheck, X } from "../icons";
import { motion } from "motion/react";
import { useState } from "react";
import { useLocation } from "react-router-dom";

import { api } from "../api";
import { ErrorNote, shortTime } from "../components/Bits";
import { describeCall } from "../components/PendingList";
import { ease, SkeletonRows, Spinner } from "../components/ui";
import type { ToolResult } from "../types";
import { useLoad } from "../useLoad";

function outcomeText(result: ToolResult): string {
  if (result.status === "ok") return "Approved. The action ran.";
  if (result.status === "denied") return "Declined. The action did not run.";
  return `Approved, but the action failed: ${result.message ?? "error"}.`;
}

export function Approve() {
  const token = decodeURIComponent(useLocation().hash.replace(/^#/, ""));
  const view = useLoad(
    () => (token ? api.inspectLink(token) : Promise.reject(new Error("This link has no token."))),
    [token],
  );
  const [busy, setBusy] = useState<boolean | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<ToolResult | null>(null);
  const v = view.data;
  const outcome = result ? outcomeText(result) : null;

  async function decide(approved: boolean) {
    setBusy(approved);
    setError(null);
    try {
      setResult(await api.resolveLink(token, approved));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="page approve-wrap" id="main">
      <div className="approve-card">
        <div className="brand" style={{ justifyContent: "center", marginBottom: 18 }}>
          <BrandMark />
          Agent Mandate
        </div>
        <motion.div
          className="card card-pad"
          initial={{ opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.35, ease }}
        >
          <h1 style={{ fontSize: "1.35rem" }}>Approval request</h1>
          <ErrorNote error={view.error} />
          {view.loading && !v && <SkeletonRows rows={4} label="Opening the approval link" />}
          {v && (
            <>
              <div className="who" style={{ marginTop: 14 }}>
                <span className="stat-icon" aria-hidden="true" style={{ width: 38, height: 38 }}>
                  <Bot size={18} />
                </span>
                <p style={{ margin: 0 }}>
                  <strong>{v.agent.name}</strong> wants to run{" "}
                  <span className="mono">{describeCall(v.action)}</span>
                  <span className="muted">
                    {" "}
                    ({v.action.action_type} on {v.action.resource})
                  </span>
                </p>
              </div>
              {v.narrative && (
                <div className="callout" style={{ marginTop: 14 }}>
                  <ShieldCheck size={16} aria-hidden="true" />
                  <span>{v.narrative}</span>
                </div>
              )}
              <dl className="details">
                <dt>For</dt>
                <dd>
                  {v.approver.name} in <span className="mono">{v.tenant_id}</span>
                </dd>
                <dt>Requested</dt>
                <dd>{shortTime(v.action.at)} UTC</dd>
                <dt>Link valid until</dt>
                <dd>
                  <Clock size={13} aria-hidden="true" /> {shortTime(v.expires_at * 1000)} UTC
                </dd>
              </dl>

              <p role="status" className="sr-only">
                {outcome}
              </p>
              <ErrorNote error={error} />
              {/* No exit animations: a resolved request must leave nothing to press. */}
              {result ? (
                <motion.div
                  key="done"
                  className={`done ${result.status === "ok" ? "callout-good" : result.status === "denied" ? "callout" : "callout-bad"}`}
                  initial={{ opacity: 0, scale: 0.96 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ type: "spring", stiffness: 380, damping: 26 }}
                  aria-hidden="true"
                >
                  <motion.span
                    initial={{ scale: 0, rotate: -30 }}
                    animate={{ scale: 1, rotate: 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 18, delay: 0.05 }}
                    style={{ display: "inline-flex" }}
                  >
                    {result.status === "denied" ? (
                      <CircleSlash size={26} />
                    ) : (
                      <CircleCheck size={26} color="var(--allow)" />
                    )}
                  </motion.span>
                  <strong>{outcome}</strong>
                </motion.div>
              ) : !v.pending ? (
                <motion.p
                  key="resolved"
                  className="note"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  This action has already been approved or declined.
                </motion.p>
              ) : (
                <motion.div key="ask" className="buttons">
                  <button
                    type="button"
                    className="primary"
                    disabled={busy !== null}
                    onClick={() => void decide(true)}
                  >
                    {busy === true ? <Spinner /> : <Check size={16} aria-hidden="true" />}
                    Approve
                  </button>
                  <button
                    type="button"
                    className="danger"
                    disabled={busy !== null}
                    onClick={() => void decide(false)}
                  >
                    {busy === false ? <Spinner /> : <X size={16} aria-hidden="true" />}
                    Decline
                  </button>
                </motion.div>
              )}
              <p className="muted small" style={{ marginTop: 16 }}>
                The link works once: after you approve or decline, it and any other link for this
                action stop working.
              </p>
            </>
          )}
        </motion.div>
      </div>
    </main>
  );
}
