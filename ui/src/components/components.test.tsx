import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { GraphElement, InstructionView, Run, TimelineEntry } from "../types";
import { ResultBadge, StatusChip } from "./Bits";
import { GraphView } from "./GraphView";
import { formatRate } from "./MetricsTable";
import { RulesList } from "./RulesList";
import { SplitRun } from "./SplitRun";

const routed = (ui: ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("ResultBadge and StatusChip", () => {
  it("show an icon and a word for every result, never colour alone", () => {
    for (const [result, word] of [
      ["allow", "Allowed"],
      ["confirm", "Needs approval"],
      ["deny", "Denied"],
    ] as const) {
      const { unmount } = render(<ResultBadge result={result} />);
      expect(screen.getByText(word)).toBeInTheDocument();
      unmount();
    }
  });

  it("flags an unauthorised execution in words", () => {
    render(<StatusChip status="executed" unauthorised />);
    expect(screen.getByText(/EXECUTED/)).toBeInTheDocument();
    expect(screen.getByText("unauthorised")).toBeInTheDocument();
  });
});

function attempt(seq: number, status: TimelineEntry["status"], unauthorised: boolean) {
  return {
    seq,
    t: seq * 1000,
    event: "agent_attempt",
    text: `Agent main calls email_delete(message_id='m-${seq}')`,
    agent: "main",
    tool: "email_delete",
    expect: "confirm",
    status,
    reason: null,
    decision_id: null,
    unauthorised,
    false_block: false,
  } satisfies TimelineEntry;
}

const RUN: Run = {
  scenario_id: "S1_rule_lost_v1",
  description: "rule lost",
  tenant_id: "run_abc",
  runs: [
    {
      kind: "naive",
      timeline: [attempt(0, "executed", true), attempt(1, "executed", true)],
      unauthorised: 2,
      false_blocks: 0,
      held: 0,
      attempts: 2,
    },
    {
      kind: "mandate",
      timeline: [attempt(0, "held", false), attempt(1, "held", false)],
      unauthorised: 0,
      false_blocks: 0,
      held: 2,
      attempts: 2,
    },
  ],
};

describe("SplitRun", () => {
  it("counts unauthorised actions only for the events shown so far", () => {
    const { rerender } = routed(<SplitRun run={RUN} shown={1} />);
    expect(screen.getByTestId("count-naive")).toHaveTextContent("1");
    expect(screen.getByTestId("count-mandate")).toHaveTextContent("0");
    rerender(
      <MemoryRouter>
        <SplitRun run={RUN} shown={2} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("count-naive")).toHaveTextContent("2");
    expect(screen.getAllByText(/CONFIRM/)).toHaveLength(2);
  });

  it("announces the latest event in a live region", () => {
    routed(<SplitRun run={RUN} shown={2} />);
    const live = document.querySelector("[aria-live='polite']");
    expect(live).toHaveTextContent("Event 2 of 2");
  });
});

function rule(
  id: string,
  status: "pending" | "active",
  trust: "trusted" | "untrusted",
): InstructionView {
  return {
    instruction: {
      id,
      effect: "allow",
      text_span: `rule ${id}`,
      status,
      created_at: 0,
      activated_at: status === "active" ? 0 : null,
      revoked_at: null,
      quarantined: false,
      lineage_trust: trust,
    },
    scope: { id: `scp_${id}`, action_type: "refund.issue", resource_pattern: "*", constraints: {} },
    agent_id: "agt_1",
  };
}

describe("RulesList", () => {
  it("never offers to confirm a rule from untrusted content", async () => {
    const onConfirm = vi.fn();
    routed(
      <RulesList
        tenantId="t"
        rows={[rule("ins_forged", "pending", "untrusted"), rule("ins_ok", "pending", "trusted")]}
        canAct
        onConfirm={onConfirm}
        onRevoke={vi.fn()}
      />,
    );
    const [forged, ok] = screen.getAllByRole("button", { name: "Confirm" });
    expect(forged).toBeDisabled();
    expect(forged).toHaveAttribute("title", expect.stringMatching(/no human origin/i));
    expect(ok).toBeEnabled();
    await userEvent.click(ok);
    expect(onConfirm).toHaveBeenCalledWith("ins_ok");
  });

  it("offers revoke for active rules and lists each rule once", () => {
    const active = rule("ins_a", "active", "trusted");
    routed(
      <RulesList
        tenantId="t"
        rows={[active, { ...active, agent_id: "agt_2" }]}
        canAct
        onConfirm={vi.fn()}
        onRevoke={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);
  });
});

const ELEMENTS: GraphElement[] = [
  {
    group: "nodes",
    data: { id: "prn_1", label: "Principal", caption: "Dana (owner)" },
    classes: "principal highlight",
  },
  {
    group: "nodes",
    data: { id: "utt_1", label: "Utterance", caption: "never delete" },
    classes: "utterance trusted",
  },
  {
    group: "edges",
    data: { id: "prn_1>SAID>utt_1", source: "prn_1", target: "utt_1", label: "SAID" },
    classes: "said",
  },
];

describe("GraphView", () => {
  it("lists the same nodes and edges as a table and marks the path", async () => {
    render(<GraphView elements={ELEMENTS} />);
    const toggle = screen.queryByRole("button", { name: "Show as table" });
    if (toggle) await userEvent.click(toggle);
    const nodes = screen.getByRole("table", { name: "Graph nodes" });
    expect(within(nodes).getByText("Dana (owner)")).toBeInTheDocument();
    expect(within(nodes).getByText("never delete")).toBeInTheDocument();
    expect(within(nodes).getAllByText("on the path")).toHaveLength(1);
    const edges = screen.getByRole("table", { name: "Graph edges" });
    expect(within(edges).getByText("SAID")).toBeInTheDocument();
  });
});

describe("formatRate", () => {
  it("reads n/a when nothing was measured", () => {
    expect(formatRate([0, 0])).toBe("n/a");
    expect(formatRate([0, 47])).toBe("0 of 47 (0.0%)");
  });
});
