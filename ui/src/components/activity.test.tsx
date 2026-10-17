import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ActivitySummary } from "../types";
import { ActivityPanel } from "./ActivityPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const HOUR = 3_600_000;
const SUMMARY: ActivitySummary = {
  since: 0,
  until: 24 * HOUR,
  bucket_ms: HOUR,
  total: 6,
  truncated: false,
  results: { allow: 3, confirm: 1, deny: 2 },
  buckets: Array.from({ length: 24 }, (_, i) =>
    i === 23 ? { start: i * HOUR, allow: 3, confirm: 1, deny: 2 } : { start: i * HOUR, allow: 0, confirm: 0, deny: 0 },
  ),
  reasons: [
    { key: "authorized", count: 3 },
    { key: "no_authority_path", count: 2 },
  ],
  actions: [{ key: "refund.issue", count: 6 }],
  agents: [{ key: "agt_1", count: 6 }],
  latency_p50_ms: 4.2,
  latency_p95_ms: 9.8,
  latency_max_ms: 12,
};

describe("activity", () => {
  it("summarises, draws, explains on hover, and switches to a table", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        urls.push(url);
        const body = url.includes("/agents") ? [{ id: "agt_1", name: "assistant", kind: "primary" }] : SUMMARY;
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
    render(<ActivityPanel tid="acme" waiting={1} />);
    expect(await screen.findByText("9.8 ms")).toBeInTheDocument();
    expect(screen.getByText("50% of decisions")).toBeInTheDocument();
    expect(screen.getByText("no rule allows it")).toBeInTheDocument();
    expect(await screen.findByText("assistant")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /6 in all/ })).toBeInTheDocument();

    const hits = document.querySelectorAll(".bar-hit");
    fireEvent.mouseEnter(hits[23]);
    const tip = await screen.findByRole("status");
    expect(tip).toHaveTextContent("Allowed3");
    expect(tip).toHaveTextContent("Denied2");

    await userEvent.click(screen.getByRole("button", { name: /Show as a table/ }));
    expect(screen.getAllByRole("row")).toHaveLength(2); // the header and the one busy hour
    await userEvent.click(screen.getByRole("radio", { name: "Last 7 days" }));
    expect(urls.some((u) => u.endsWith("/activity?hours=168"))).toBe(true);
  });
});

describe("the axis", () => {
  it("tops out just above the tallest bar", async () => {
    const { niceMax } = await import("./ActivityPanel");
    expect([1, 3, 13, 40, 41, 230].map(niceMax)).toEqual([2, 4, 16, 40, 50, 300]);
  });
});
