// Live updates for one tenant from GET /v1/tenants/:tid/events (server-sent events).
// The proxy adds the API key, so a plain EventSource works. The browser reconnects on its
// own when the server ends a stream; without EventSource the page simply is not live.

import { useEffect, useRef, useState } from "react";

export type LiveStatus = "off" | "connecting" | "live" | "reconnecting";

export interface LiveHandlers {
  decisions?: (data: { decisions: number; new: number }) => void;
  approvals?: (data: { pending: string[]; added: string[] }) => void;
  rules?: () => void;
}

export function useLiveEvents(tenantId: string, handlers: LiveHandlers): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>("off");
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    if (typeof EventSource === "undefined" || !tenantId) return;
    setStatus("connecting");
    const source = new EventSource(`/v1/tenants/${encodeURIComponent(tenantId)}/events`);
    const on = (name: string, run: (data: never) => void) =>
      source.addEventListener(name, (event) => {
        setStatus("live");
        run(JSON.parse((event as MessageEvent<string>).data || "{}") as never);
      });
    on("ready", () => undefined);
    on("decisions", (data) => latest.current.decisions?.(data));
    on("approvals", (data) => latest.current.approvals?.(data));
    on("rules", () => latest.current.rules?.());
    source.addEventListener("unavailable", () => setStatus("reconnecting"));
    source.onerror = () =>
      setStatus(source.readyState === EventSource.CLOSED ? "off" : "reconnecting");
    return () => {
      source.close();
      setStatus("off");
    };
  }, [tenantId]);

  return status;
}
