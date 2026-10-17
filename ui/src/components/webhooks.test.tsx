import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WebhookInfo } from "../types";
import { WebhooksPanel } from "./WebhooksPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const HOOK: WebhookInfo = {
  id: "whk_1",
  tenant_id: "acme",
  name: "Owner's channel",
  url: "https://hooks.slack.com/…tXYZ",
  kind: "slack",
  events: ["approval.requested"],
  enabled: true,
  created_at: 0,
  created_by: "user:usr_1",
  last_delivery_at: Date.now() - 60_000,
  last_ok: false,
  failures: 3,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function stub(hooks: WebhookInfo[]) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/deliveries"))
        return json([
          { id: "dlv_1", webhook_id: "whk_1", event: "approval.requested", at: Date.now(), ok: false,
            attempts: 3, status: 503, error: "HTTP 503", duration_ms: 1500, subject: "act_9" },
        ]); // prettier-ignore
      if (url.endsWith("/test"))
        return json({ id: "dlv_2", ok: true, duration_ms: 42, event: "webhook.test", attempts: 1 });
      if (method === "POST" && url.endsWith("/webhooks"))
        return json({ ...HOOK, id: "whk_2", kind: "json", secret: "whsec_abc" }, 201);
      if (url.endsWith("/webhooks")) return json(hooks);
      return json(HOOK);
    }),
  );
  return calls;
}

describe("alerts", () => {
  it("shows a failing webhook, its log, and sends a test", async () => {
    const calls = stub([HOOK]);
    render(<WebhooksPanel tid="acme" />);
    expect(await screen.findByText("Owner's channel")).toBeInTheDocument();
    expect(screen.getByText(/Last attempt failed .* · 3 failures in a row/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delivery log" }));
    expect(await screen.findByText("HTTP 503")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Send test/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/webhooks/whk_1/test"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: /Pause/ }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: false }),
    );
  });

  it("adds a JSON webhook and shows its signing secret once", async () => {
    const calls = stub([]);
    render(<WebhooksPanel tid="acme" />);
    expect(await screen.findByText("No alerts yet")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /Add alert/ })[0]);
    await userEvent.click(screen.getByText("JSON (any HTTPS endpoint)"));
    await userEvent.type(screen.getByLabelText("URL"), "https://example.com/hook");
    await userEvent.click(screen.getByRole("button", { name: /^Add alert$/ }));
    expect(await screen.findByText("whsec_abc")).toBeInTheDocument();
    const made = calls.find((c) => c.method === "POST" && c.url.endsWith("/webhooks"));
    expect(made?.body).toEqual({ name: "Owner's channel", url: "https://example.com/hook", kind: "json" });
  });
});
