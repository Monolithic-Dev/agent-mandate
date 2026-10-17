// A tenant's rules with their state. Confirm is offered only for pending rules with a human
// origin; a rule drawn from untrusted content can never be confirmed (AUTH-006).

import { BadgeCheck, CircleSlash, ScrollText } from "../icons";
import { Link } from "react-router-dom";

import type { InstructionView } from "../types";
import { Chip, relativeTime, shortTime } from "./Bits";
import { EmptyState } from "./ui";

export interface RulesListProps {
  tenantId: string;
  rows: InstructionView[];
  canAct: boolean;
  busy?: string | null;
  onConfirm: (instructionId: string) => void;
  onRevoke: (instructionId: string) => void;
}

const EFFECT_WORD = { allow: "Allow", confirm: "Ask first", deny: "Deny" } as const;

export function RulesList({ tenantId, rows, canAct, busy, onConfirm, onRevoke }: RulesListProps) {
  // The API returns one row per agent a rule applies to; show each rule once.
  const rules = new Map<string, { view: InstructionView; agents: number }>();
  for (const view of rows) {
    const seen = rules.get(view.instruction.id);
    rules.set(view.instruction.id, { view, agents: (seen?.agents ?? 0) + 1 });
  }
  if (rules.size === 0) {
    return (
      <EmptyState icon={ScrollText} title="No rules yet.">
        Rules appear when the owner states them in plain language.
      </EmptyState>
    );
  }
  return (
    <div className="table-wrap">
      <table className="stack">
        <thead>
          <tr>
            <th scope="col">Rule</th>
            <th scope="col">Covers</th>
            <th scope="col">State</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {[...rules.values()].map(({ view: { instruction: i, scope } }) => {
            const untrusted = i.lineage_trust === "untrusted";
            const pending = i.status === "pending";
            return (
              <tr key={i.id} className={untrusted ? "inert" : undefined}>
                <td data-label="Rule">
                  <Link to={`/tenants/${tenantId}/instructions/${i.id}`}>
                    {EFFECT_WORD[i.effect]}: “{i.text_span}”
                  </Link>
                </td>
                <td className="mono" data-label="Covers">
                  {scope.action_type} on {scope.resource_pattern}
                  {scope.constraints?.max_amount != null &&
                    ` (up to ${scope.constraints.max_amount})`}
                </td>
                <td data-label="State">
                  <span className="chips">
                    <Chip kind={`state-${i.status}`}>{i.status}</Chip>
                    <Chip kind={`trust-${i.lineage_trust}`}>
                      {untrusted ? "⚠ untrusted origin" : `${i.lineage_trust} origin`}
                    </Chip>
                    {i.quarantined && <Chip kind="state-quarantined">quarantined</Chip>}
                    {i.activated_via === "auto" && <Chip kind="flag-info">auto-activated</Chip>}
                    {i.valid_to != null && (
                      <Chip kind={i.valid_to <= Date.now() ? "state-revoked" : "flag-info"}>
                        <span title={shortTime(i.valid_to)}>
                          {i.valid_to <= Date.now()
                            ? "expired"
                            : `expires ${relativeTime(i.valid_to)}`}
                        </span>
                      </Chip>
                    )}
                  </span>
                </td>
                <td className="actions">
                  {pending && (
                    <button
                      type="button"
                      className="sm"
                      disabled={!canAct || untrusted || busy === i.id}
                      title={
                        untrusted
                          ? "No human origin: a rule from untrusted content cannot be confirmed"
                          : undefined
                      }
                      aria-describedby={untrusted ? `why-${i.id}` : undefined}
                      onClick={() => onConfirm(i.id)}
                    >
                      <BadgeCheck size={14} aria-hidden="true" /> Confirm
                    </button>
                  )}
                  {untrusted && pending && (
                    <span id={`why-${i.id}`} className="muted small">
                      no human origin
                    </span>
                  )}
                  {i.status === "active" && (
                    <button
                      type="button"
                      className="danger sm"
                      disabled={!canAct || busy === i.id}
                      onClick={() => onRevoke(i.id)}
                    >
                      <CircleSlash size={14} aria-hidden="true" /> Revoke
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
