import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, toApiError } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("toApiError", () => {
  it("maps the API's error body to code, message and request id", () => {
    const error = toApiError(404, "Not Found", {
      error: { code: "not_found", message: "no such tenant", request_id: "req_1" },
    });
    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message, error.requestId]).toEqual([
      404,
      "not_found",
      "no such tenant",
      "req_1",
    ]);
  });

  it("falls back to the HTTP status when the body is not the API's", () => {
    const error = toApiError(502, "Bad Gateway", null);
    expect([error.code, error.message]).toEqual(["http_502", "Bad Gateway"]);
  });
});

describe("api", () => {
  it("throws an ApiError for a failed request and sends JSON bodies", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: "forbidden", message: "viewer" } }), {
          status: 403,
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.run("S1_rule_lost_v1")).rejects.toMatchObject({ code: "forbidden" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/v1/runs");
    expect(JSON.parse(String(init.body))).toEqual({
      scenario_id: "S1_rule_lost_v1",
      kinds: ["naive", "mandate"],
    });
  });

  it("encodes path segments", async () => {
    const fetchMock = vi.fn(async () => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.graph("acme", "dec_1");
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(
      "/v1/tenants/acme/graph?highlight=dec_1",
    );
  });
});
