import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { describeCall, PendingList } from "../components/PendingList";
import type { Action, ActionRow, LinkView } from "../types";
import { Approve } from "./Approve";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ACTION: Action = {
  id: "act_1",
  action_type: "email.delete",
  resource: "inbox/m-1",
  status: "pending",
  at: 0,
  args: { tool: "email_delete", tool_args: { message_id: "m-1" } },
};

const ROW: ActionRow = { action: ACTION, agent_id: "agt_1", decision_id: "dec_1" };

describe("PendingList", () => {
  it("describes the call as the agent made it", () => {
    expect(describeCall(ACTION)).toBe('email_delete(message_id="m-1")');
    expect(describeCall({ ...ACTION, args: undefined })).toBe("email.delete inbox/m-1");
  });

  it("offers approve, decline and a link, and shows why it is held", async () => {
    const onResolve = vi.fn();
    const onLink = vi.fn();
    render(
      <MemoryRouter>
        <PendingList
          tenantId="acme"
          rows={[ROW]}
          agentNames={{ agt_1: "main" }}
          canAct
          links={{ act_1: { token: "apl1.x.y", expires_at: 60, path: "/approve#apl1.x.y" } }}
          onResolve={onResolve}
          onLink={onLink}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("main")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "why it is held" })).toHaveAttribute(
      "href",
      "/tenants/acme/decisions/dec_1",
    );
    await userEvent.click(screen.getByRole("button", { name: /^Approve email_delete/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Decline email_delete/ }));
    await userEvent.click(screen.getByRole("button", { name: /Make an approval link/ }));
    expect(onResolve.mock.calls).toEqual([
      ["act_1", true],
      ["act_1", false],
    ]);
    expect(onLink).toHaveBeenCalledWith("act_1");
    expect(screen.getByRole("textbox", { name: /single use/ })).toHaveValue(
      `${window.location.origin}/approve#apl1.x.y`,
    );
  });

  it("says so when nothing is waiting", () => {
    render(
      <PendingList
        tenantId="acme"
        rows={[]}
        agentNames={{}}
        canAct
        links={{}}
        onResolve={vi.fn()}
        onLink={vi.fn()}
      />,
    );
    expect(screen.getByText("Nothing is waiting for approval.")).toBeInTheDocument();
  });
});

const VIEW: LinkView = {
  tenant_id: "acme",
  action: ACTION,
  agent: { id: "agt_1", name: "main", kind: "primary" },
  decision_id: "dec_1",
  narrative: "Needs approval: a rule requires the owner's confirmation.",
  approver: { id: "prn_1", name: "Dana", role: "owner" },
  expires_at: 900,
  pending: true,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function openLink() {
  render(
    <MemoryRouter initialEntries={["/approve#apl1.tok.sig"]}>
      <Approve />
    </MemoryRouter>,
  );
}

describe("Approve", () => {
  it("shows the request, posts the token in the body, and reports the outcome", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith("/inspect") ? json(VIEW) : json({ status: "ok", approval_id: "act_1" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    openLink();
    expect(await screen.findByText(/wants to run/)).toHaveTextContent(
      'main wants to run email_delete(message_id="m-1")',
    );
    expect(screen.getByText(/Needs approval/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Approved. The action ran.");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([url]) => url)).toEqual([
      "/v1/approval-links/inspect",
      "/v1/approval-links/resolve",
    ]);
    expect(JSON.parse(String(calls[1][1].body))).toEqual({
      token: "apl1.tok.sig",
      approved: true,
    });
  });

  it("offers nothing to press once the action is resolved", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ ...VIEW, pending: false })),
    );
    openLink();
    expect(await screen.findByText(/already been approved or declined/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("explains a bad or expired link", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          {
            error: {
              code: "unauthorized",
              message: "this approval link is not valid or has expired",
            },
          },
          401,
        ),
      ),
    );
    openLink();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("not valid or has expired"),
    );
  });
});
