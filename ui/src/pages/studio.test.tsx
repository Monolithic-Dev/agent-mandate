import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TestAuth } from "../auth";
import type { Preview } from "../types";
import { describeRule, duration, Studio } from "./Studio";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("studio words", () => {
  it("says how long a rule lasts", () => {
    expect(duration(7_200_000)).toBe("2 hours");
    expect(duration(3_600_000)).toBe("1 hour");
    expect(duration(604_800_000)).toBe("1 week");
    expect(duration(30 * 60_000)).toBe("30 minutes");
  });

  it("describes a rule in plain words", () => {
    expect(describeRule({ action_type: "refund.issue", resource_pattern: "*", max_amount: 1000 })).toBe(
      "issue refunds up to $1,000",
    );
    expect(describeRule({ action_type: "email.read", resource_pattern: "inbox/*", max_amount: null })).toBe(
      "read email in inbox/*",
    );
  });
});

const PREVIEW: Preview = {
  agent_ids: ["agt_main"],
  rules: [
    {
      effect: "allow",
      action_type: "refund.issue",
      resource_pattern: "*",
      max_amount: 500,
      valid_for_ms: 7_200_000,
      valid_to: 1,
      needs_confirmation: true,
      text_span: "For the next 2 hours, you may issue refunds up to $500",
    },
  ],
  unparsed: ["Be nice"],
  conflicts: [
    {
      rule: 0,
      instruction_id: "ins_old",
      text_span: "Never issue refunds",
      effect: "deny",
      action_type: "refund.issue",
      resource_pattern: "*",
      max_amount: null,
      kind: "contradicts",
    },
  ],
  evaluated: 2,
  changes: [
    {
      agent_id: "agt_main",
      action_type: "refund.issue",
      resource: "order/1",
      amount: 300,
      example_decision_id: "dec_1",
      was_result: "deny",
      was_reason: "explicit_deny",
      now_result: "allow",
      now_reason: "authorized",
      result_changed: true,
    },
  ],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function renderStudio(role: "admin" | "viewer" = "admin") {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/principals")) return json([{ id: "prn_owner", name: "Dana", role: "owner" }]);
      if (url.endsWith("/agents")) return json([{ id: "agt_main", name: "main", kind: "primary" }]);
      if (url.endsWith("/utterances/preview")) return json(PREVIEW);
      if (url.endsWith("/utterances"))
        return json({
          utterance_id: "utt_1",
          instructions: [{ instruction: { id: "ins_new" }, needs_confirmation: true }],
          unparsed: [],
        });
      if (url.endsWith("/confirm")) return json({ id: "ins_new" });
      if (url.endsWith("/check"))
        return json({
          decision_id: null,
          result: "confirm",
          reason: "confirm_rule",
          recorded: false,
          approval_required: true,
          path: [{ type: "Principal", id: "prn_owner", note: "Dana (owner)" }],
          ignored: [],
          latency_ms: 3.2,
        });
      return json([]);
    }),
  );
  render(
    <MemoryRouter initialEntries={["/tenants/acme/studio"]}>
      <TestAuth me={{ role }}>
        <Routes>
          <Route path="/tenants/:tid/studio" element={<Studio />} />
        </Routes>
      </TestAuth>
    </MemoryRouter>,
  );
  return calls;
}

describe("the rule studio", () => {
  it("previews a sentence: rules, what is not understood, conflicts and what would change", async () => {
    const calls = renderStudio();
    await userEvent.type(await screen.findByLabelText("What the owner says"), "anything");
    expect(await screen.findByText("This would make 1 rule")).toBeInTheDocument();
    expect(screen.getByText("issue refunds up to $500")).toBeInTheDocument();
    expect(screen.getByText(/for 2 hours/)).toBeInTheDocument();
    expect(screen.getByText("needs confirmation")).toBeInTheDocument();
    expect(screen.getByText("“Be nice”")).toBeInTheDocument();
    expect(screen.getByText("Contradicts")).toBeInTheDocument();
    expect(screen.getByText("Would change 1 of 2 recent requests")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save and confirm as the owner/ })).toBeEnabled();
    const preview = calls.find((c) => c.url.endsWith("/utterances/preview"));
    expect(preview?.body).toMatchObject({ principal_id: "prn_owner", text: "anything" });
  });

  it("saves and confirms as the owner from the primary button", async () => {
    const calls = renderStudio();
    await userEvent.type(await screen.findByLabelText("What the owner says"), "anything");
    await userEvent.click(await screen.findByRole("button", { name: /Save and confirm as the owner/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/instructions/ins_new/confirm"))).toBe(true));
    const said = calls.find((c) => c.url.endsWith("/utterances"));
    expect(said?.body).toMatchObject({ principal_id: "prn_owner", text: "anything", channel: "owner_direct" });
    expect(screen.getByLabelText("What the owner says")).toHaveValue("");
  });

  it("tries an action as a dry run and shows the chain", async () => {
    const calls = renderStudio();
    await userEvent.click(await screen.findByRole("button", { name: "Check" }));
    expect(await screen.findByText(/because a rule says ask the owner first/)).toBeInTheDocument();
    expect(screen.getByText("Dana (owner)", { exact: false })).toBeInTheDocument();
    const check = calls.find((c) => c.url.endsWith("/check"));
    expect(check?.body).toMatchObject({ action_type: "refund.issue", args: { amount: 250 }, dry_run: true });
  });

  it("lets a viewer look but not preview, save or check", async () => {
    renderStudio("viewer");
    await userEvent.type(await screen.findByLabelText("What the owner says"), "anything");
    expect(screen.getByText("Previewing needs the operator role or above.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: /Save rule/ })).toBeDisabled());
  });
});
