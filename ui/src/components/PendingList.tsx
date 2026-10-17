// Actions held for the owner's approval: what the agent wants to run, why it is waiting, and
// approve, decline or a link the owner can use elsewhere. Rows animate in and out as actions
// arrive (live) and are resolved.

import { Check, Copy, Inbox, Link2, X } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import type { Action, ActionRow, ApprovalLink } from "../types";
import { relativeTime, shortTime } from "./Bits";
import { EmptyState, Tip } from "./ui";

export interface PendingListProps {
  tenantId: string;
  rows: ActionRow[];
  agentNames: Record<string, string>;
  canAct: boolean;
  busy?: string | null;
  links: Record<string, ApprovalLink>;
  onResolve: (actionId: string, approved: boolean) => void;
  onLink: (actionId: string) => void;
}

/** The tool call as the agent made it, for example email_delete(message_id="m-1"). */
export function describeCall(action: Action): string {
  const tool = action.args?.tool;
  if (!tool) return `${action.action_type} ${action.resource}`;
  const args = Object.entries(action.args?.tool_args ?? {})
    .map(([name, value]) => `${name}=${JSON.stringify(value)}`)
    .join(", ");
  return `${tool}(${args})`;
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Approval link copied", { description: "It works once and then expires." });
  } catch {
    toast.error("Could not copy: select the link and copy it yourself.");
  }
}

export function PendingList({
  tenantId,
  rows,
  agentNames,
  canAct,
  busy,
  links,
  onResolve,
  onLink,
}: PendingListProps) {
  if (rows.length === 0) {
    return (
      <EmptyState icon={Inbox} title="Nothing is waiting for approval.">
        Held actions appear here the moment an agent asks.
      </EmptyState>
    );
  }
  return (
    <div className="table-wrap">
      <table className="stack">
        <caption className="sr-only">Actions waiting for the owner's approval</caption>
        <thead>
          <tr>
            <th scope="col">Requested</th>
            <th scope="col">Agent</th>
            <th scope="col">Wants to run</th>
            <th scope="col" style={{ textAlign: "right" }}>
              Decision
            </th>
          </tr>
        </thead>
        <tbody>
          <AnimatePresence initial={false}>
            {rows.map(({ action, agent_id, decision_id }) => {
              const link = links[action.id];
              const call = describeCall(action);
              const url = link ? `${window.location.origin}${link.path}` : "";
              return (
                <motion.tr
                  key={action.id}
                  layout
                  initial={{ opacity: 0, backgroundColor: "var(--accent-soft)" }}
                  animate={{ opacity: 1, backgroundColor: "rgba(0,0,0,0)" }}
                  exit={{ opacity: 0, x: 24 }}
                  transition={{ duration: 0.35 }}
                >
                  <td className="muted small" title={shortTime(action.at)} data-label="Requested">
                    {relativeTime(action.at)}
                  </td>
                  <td data-label="Agent">
                    <span className="chip">{agentNames[agent_id] ?? agent_id}</span>
                  </td>
                  <td data-label="Wants to run">
                    <span className="mono">{call}</span>
                    {decision_id && (
                      <>
                        {" "}
                        <Link
                          className="small"
                          to={`/tenants/${tenantId}/decisions/${decision_id}`}
                        >
                          why it is held
                        </Link>
                      </>
                    )}
                    <AnimatePresence>
                      {link && (
                        <motion.div
                          className="link-out"
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                        >
                          <label className="small">
                            Approval link, single use, valid until{" "}
                            {shortTime(link.expires_at * 1000)} UTC
                            <input
                              readOnly
                              value={url}
                              onFocus={(event) => event.currentTarget.select()}
                            />
                          </label>
                          <Tip content="Copy the link">
                            <button
                              type="button"
                              className="icon sm"
                              style={{ alignSelf: "flex-end" }}
                              aria-label="Copy the approval link"
                              onClick={() => void copy(url)}
                            >
                              <Copy size={14} aria-hidden="true" />
                            </button>
                          </Tip>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </td>
                  <td className="actions">
                    <button
                      type="button"
                      className="primary sm"
                      disabled={!canAct || busy === action.id}
                      aria-label={`Approve ${call}`}
                      onClick={() => onResolve(action.id, true)}
                    >
                      <Check size={14} aria-hidden="true" /> Approve
                    </button>
                    <button
                      type="button"
                      className="danger sm"
                      disabled={!canAct || busy === action.id}
                      aria-label={`Decline ${call}`}
                      onClick={() => onResolve(action.id, false)}
                    >
                      <X size={14} aria-hidden="true" /> Decline
                    </button>
                    <Tip content="Make a single-use link the owner can approve from">
                      <button
                        type="button"
                        className="ghost sm"
                        disabled={!canAct || busy === action.id}
                        aria-label={`Make an approval link for ${call}`}
                        onClick={() => onLink(action.id)}
                      >
                        <Link2 size={14} aria-hidden="true" /> Link
                      </button>
                    </Tip>
                  </td>
                </motion.tr>
              );
            })}
          </AnimatePresence>
        </tbody>
      </table>
    </div>
  );
}
