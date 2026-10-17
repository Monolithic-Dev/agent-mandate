import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type LiveHandlers, useLiveEvents } from "./useLiveEvents";

class FakeSource {
  static CLOSED = 2;
  static last: FakeSource | null = null;
  readonly url: string;
  readyState = 0;
  closed = false;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();

  constructor(url: string) {
    this.url = url;
    FakeSource.last = this;
  }

  addEventListener(name: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }

  emit(name: string, data: unknown = {}) {
    for (const listener of this.listeners.get(name) ?? []) {
      listener(new MessageEvent(name, { data: JSON.stringify(data) }));
    }
  }

  close() {
    this.closed = true;
  }
}

function Probe({ handlers }: { handlers: LiveHandlers }) {
  return <p>{useLiveEvents("acme", handlers)}</p>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useLiveEvents", () => {
  it("routes each event to its handler and reports the connection", () => {
    vi.stubGlobal("EventSource", FakeSource);
    const handlers = { decisions: vi.fn(), approvals: vi.fn(), rules: vi.fn() };
    const { unmount } = render(<Probe handlers={handlers} />);
    const source = FakeSource.last!;
    expect(source.url).toBe("/v1/tenants/acme/events");
    expect(screen.getByText("connecting")).toBeInTheDocument();

    act(() => source.emit("ready", { decisions: 0, pending: [] }));
    expect(screen.getByText("live")).toBeInTheDocument();
    act(() => {
      source.emit("decisions", { decisions: 1, new: 1 });
      source.emit("approvals", { pending: ["act_1"], added: ["act_1"] });
      source.emit("rules");
    });
    expect(handlers.decisions).toHaveBeenCalledWith({ decisions: 1, new: 1 });
    expect(handlers.approvals).toHaveBeenCalledWith({ pending: ["act_1"], added: ["act_1"] });
    expect(handlers.rules).toHaveBeenCalledOnce();

    act(() => source.emit("unavailable", { code: "graph_unavailable" }));
    expect(screen.getByText("reconnecting")).toBeInTheDocument();
    unmount();
    expect(source.closed).toBe(true);
  });

  it("is simply off where EventSource does not exist", () => {
    vi.stubGlobal("EventSource", undefined);
    render(<Probe handlers={{}} />);
    expect(screen.getByText("off")).toBeInTheDocument();
  });
});
