// Flow B: why was this allowed or blocked? The narrative, the path, the verification, and
// the path highlighted on the graph.

import type { Icon } from "../icons";
import { Bot, CheckCircle2, FileText, Gavel, GitBranch, Link2, ListTree, MessageSquareText, ScrollText, ShieldCheck, ShieldX, StickyNote, User, XCircle } from "../icons";
import { motion } from "motion/react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import { ErrorNote, ResultBadge, shortTime } from "../components/Bits";
import { GraphView } from "../components/GraphView";
import { Card, CardHead, ease, PageHeader, SkeletonRows } from "../components/ui";
import { useElementLinks } from "../graphLinks";
import { useLoad } from "../useLoad";

const HOP_ICONS: Record<string, Icon> = {
  Principal: User,
  Utterance: MessageSquareText,
  Summary: FileText,
  Instruction: ScrollText,
  Delegation: GitBranch,
  Agent: Bot,
  Note: StickyNote,
};

export function DecisionPage() {
  const { tid = "", did = "" } = useParams();
  const explained = useLoad(() => api.explain(tid, did), [tid, did]);
  const verified = useLoad(() => api.verify(tid, did), [tid, did]);
  const graph = useLoad(() => api.graph(tid, did), [tid, did]);
  const select = useElementLinks(tid);
  const e = explained.data;

  return (
    <div className="page">
      <ErrorNote error={explained.error} />
      {explained.loading && !e && (
        <Card>
          <SkeletonRows rows={5} label="Loading the decision" />
        </Card>
      )}
      {e && (
        <>
          <PageHeader
            eyebrow={
              <>
                <Gavel size={14} aria-hidden="true" /> Decision
              </>
            }
            title={
              <>
                {e.action.action_type} <span className="mono">{e.action.resource}</span>
              </>
            }
            badge={<ResultBadge result={e.decision.result} />}
            description={
              <span className="muted small">
                Decided {shortTime(e.decision.at)} · reason {e.decision.reason.replaceAll("_", " ")}{" "}
                · {e.decision.latency_ms.toFixed(1)} ms ·{" "}
                <span className="mono">{e.decision.id}</span>
              </span>
            }
          />

          <motion.div
            className={`callout ${e.decision.result === "allow" ? "callout-good" : e.decision.result === "deny" ? "callout-bad" : ""}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease }}
          >
            {e.decision.result === "deny" ? (
              <ShieldX size={18} aria-hidden="true" />
            ) : (
              <ShieldCheck size={18} aria-hidden="true" />
            )}
            <p className="lead" style={{ margin: 0 }}>
              {e.narrative}
            </p>
          </motion.div>

          <div
            style={{
              display: "grid",
              gap: 16,
              gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
              marginTop: 16,
            }}
          >
            <Card delay={0.05}>
              <CardHead
                icon={ListTree}
                title="The chain"
                hint="from the owner's words to the agent"
              />
              <div className="card-body">
                <ol className="path">
                  {e.decision.path.map((hop, index) => {
                    const Icon = HOP_ICONS[hop.type] ?? Link2;
                    return (
                      <motion.li
                        key={`${hop.id}-${index}`}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.3, ease, delay: 0.08 + index * 0.07 }}
                      >
                        <span className="hop-dot" aria-hidden="true">
                          <Icon size={15} />
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
                {e.decision.ignored.length > 0 && (
                  <>
                    <h3 style={{ margin: "16px 0 6px" }}>Ignored</h3>
                    <ul className="list">
                      {e.decision.ignored.map((item) => (
                        <li key={item.id}>
                          <span className="chip flag-warn">⚠ {item.why.replaceAll("_", " ")}</span>{" "}
                          <Link className="mono" to={`/tenants/${tid}/instructions/${item.id}`}>
                            {item.id}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            </Card>

            <Card delay={0.1}>
              <CardHead
                icon={ShieldCheck}
                title="Verified against the graph"
                right={
                  verified.data &&
                  (verified.data.ok ? (
                    <span className="chip status-executed">✓ every claim checks out</span>
                  ) : (
                    <span className="chip flag-bad">✕ some claims do not hold</span>
                  ))
                }
              />
              <div className="card-body">
                <ErrorNote error={verified.error} />
                {verified.loading && !verified.data && (
                  <SkeletonRows rows={4} label="Re-checking every claim" />
                )}
                {verified.data && (
                  <ul className="checks">
                    {verified.data.checks.map((check, index) => (
                      <motion.li
                        key={check.name}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.15 + index * 0.03 }}
                      >
                        {check.ok ? (
                          <CheckCircle2 size={16} className="check-ok" aria-hidden="true" />
                        ) : (
                          <XCircle size={16} className="check-bad" aria-hidden="true" />
                        )}
                        <span className="sr-only">{check.ok ? "passed" : "failed"}</span>
                        <span>
                          {check.name.replaceAll("_", " ")}
                          {check.detail && <span className="muted small"> {check.detail}</span>}
                        </span>
                      </motion.li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>
        </>
      )}

      <div className="section">
        <div className="section-head">
          <h2>On the graph</h2>
          <span className="hint">the decision's path is highlighted</span>
        </div>
        <ErrorNote error={graph.error} />
        {graph.loading && !graph.data && <div className="card skeleton" style={{ height: 460 }} />}
        {graph.data && (
          <GraphView
            elements={graph.data.elements}
            truncated={graph.data.truncated}
            onSelect={select}
          />
        )}
      </div>
    </div>
  );
}
