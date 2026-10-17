import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import type { GraphElement } from "../types";
import { GraphExplorer } from "./GraphExplorer";

afterEach(cleanup);

const node = (id: string, label: string, caption: string): GraphElement => ({
  group: "nodes",
  data: { id, label, caption },
  classes: label.toLowerCase(),
});
const edge = (source: string, label: string, target: string): GraphElement => ({
  group: "edges",
  data: { id: `${source}>${label}>${target}`, source, target, label },
  classes: label.toLowerCase(),
});

const GRAPH: GraphElement[] = [
  node("prn_1", "Principal", "Dana (owner)"),
  node("utt_1", "Utterance", "You may read my email"),
  node("ins_1", "Instruction", "allow: read my email"),
  node("ins_2", "Instruction", "allow: archive newsletters"),
  node("agt_1", "Agent", "main (primary)"),
  node("act_1", "Action", "email.read inbox/m-1"),
  node("dec_1", "Decision", "ALLOW: authorized"),
  edge("prn_1", "SAID", "utt_1"),
  edge("utt_1", "EXPRESSES", "ins_1"),
  edge("ins_1", "APPLIES_TO", "agt_1"),
  edge("ins_2", "APPLIES_TO", "agt_1"),
  edge("act_1", "PROPOSED_BY", "agt_1"),
  edge("dec_1", "CHECKED", "act_1"),
  edge("dec_1", "USED", "ins_1"),
];

let search = "";
function Where() {
  search = useLocation().search;
  return null;
}

function renderAt(query = "") {
  return render(
    <MemoryRouter initialEntries={[`/tenants/acme${query}`]}>
      <GraphExplorer tid="acme" elements={GRAPH} truncated={false} />
      <Where />
    </MemoryRouter>,
  );
}

const nodeRows = () =>
  within(screen.getByRole("table", { name: "Graph nodes" }))
    .getAllByRole("row")
    .slice(1);

describe("graph explorer", () => {
  it("finds a node from the keyboard, then traces its lineage", async () => {
    renderAt();
    const box = screen.getByRole("combobox", { name: "Find a node in the graph" });
    await userEvent.type(box, "authorized");
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(1);
    await userEvent.keyboard("{Enter}");
    expect(search).toContain("node=dec_1");

    const inspector = screen.getByRole("complementary", { name: "Selected node" });
    expect(within(inspector).getByRole("heading", { name: "ALLOW: authorized" })).toBeVisible();
    expect(within(inspector).getByRole("link", { name: /Open/ })).toHaveAttribute(
      "href",
      "/tenants/acme/decisions/dec_1",
    );

    await userEvent.click(within(inspector).getByRole("button", { name: /Trace lineage/ }));
    expect(search).toContain("trace=1");
    const cameFrom = within(inspector).getByRole("region", { name: "Came from" });
    expect(within(cameFrom).getByText("Dana (owner)")).toBeInTheDocument();
    expect(within(cameFrom).getByText("allow: read my email")).toBeInTheDocument();
    // The agent's other rule played no part in this decision.
    expect(within(inspector).queryByText("allow: archive newsletters")).toBeNull();
    // The table view narrows to the lineage too.
    expect(nodeRows()).toHaveLength(6);
  });

  it("opens straight onto a traced node from a shared link", async () => {
    renderAt("?tab=graph&node=prn_1&trace=1");
    const inspector = screen.getByRole("complementary", { name: "Selected node" });
    expect(within(inspector).getByRole("button", { name: /Stop tracing/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const ledTo = within(inspector).getByRole("region", { name: "Led to" });
    expect(within(ledTo).getByText("ALLOW: authorized")).toBeInTheDocument();
    await userEvent.click(within(inspector).getByRole("button", { name: "Clear the selection" }));
    expect(search).toBe("?tab=graph");
  });

  it("hides and shows a kind of node", async () => {
    renderAt();
    expect(nodeRows()).toHaveLength(7);
    const rules = screen.getByRole("button", { name: /Rules/ });
    expect(rules).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(rules);
    expect(rules).toHaveAttribute("aria-pressed", "false");
    expect(nodeRows()).toHaveLength(5);
  });
});
