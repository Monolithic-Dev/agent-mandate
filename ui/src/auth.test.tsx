import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, SIGNED_OUT_EVENT } from "./api";
import { AuthProvider, TestAuth, useAuth } from "./auth";
import { describe as describeEvent } from "./pages/Audit";
import { SignIn } from "./pages/SignIn";
import { Users } from "./pages/Users";
import type { AuditEvent, ConsoleUser, Me } from "./types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DANA: Me = {
  kind: "user",
  id: "usr_1",
  name: "Dana Lee",
  email: "dana@example.com",
  role: "admin",
  tenants: null,
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

const UNAUTHORISED = { error: { code: "unauthorized", message: "missing or invalid API key" } };

/** What the console shows: the sign-in screen, or who is signed in. */
function Shell() {
  const { status, me } = useAuth();
  if (status === "signed-out") return <SignIn />;
  if (status === "signed-in") return <p>Signed in as {me?.name}</p>;
  return <p>{status}</p>;
}

describe("signing in", () => {
  it("shows the sign-in screen without a session, then signs in", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/v1/auth/me") return json(401, UNAUTHORISED);
      if (url === "/v1/auth/login") {
        const body = JSON.parse(String(init?.body)) as { password: string };
        return body.password === "right password!"
          ? json(200, DANA)
          : json(401, { error: { code: "unauthorized", message: "no" } });
      }
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <AuthProvider>
        <Shell />
      </AuthProvider>,
    );
    const email = await screen.findByLabelText("Email");
    await userEvent.type(email, "dana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That email and password do not match an active account.",
    );
    expect(screen.getByLabelText("Password")).toHaveValue("");

    await userEvent.type(screen.getByLabelText("Password"), "right password!");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Signed in as Dana Lee")).toBeInTheDocument();

    const [, init] = fetchMock.mock.calls.find(([url]) => url === "/v1/auth/login") as [
      string,
      RequestInit,
    ];
    expect((init.headers as Record<string, string>)["X-Mandate-Client"]).toBe("console");
  });

  it("lets the password be shown, and says so", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(401, UNAUTHORISED)));
    render(
      <AuthProvider>
        <Shell />
      </AuthProvider>,
    );
    const password = await screen.findByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show the password" }));
    expect(password).toHaveAttribute("type", "text");
  });

  it("goes back to the sign-in screen when the session ends", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (url === "/v1/auth/me" ? json(200, DANA) : json(401, UNAUTHORISED))),
    );
    render(
      <AuthProvider>
        <Shell />
      </AuthProvider>,
    );
    expect(await screen.findByText("Signed in as Dana Lee")).toBeInTheDocument();
    await expect(api.tenants()).rejects.toMatchObject({ status: 401 });
    expect(await screen.findByText("Your session ended. Sign in again to continue.")).toBeInTheDocument();
  });

  it("treats a console key as already signed in", async () => {
    const key: Me = { ...DANA, kind: "key", id: "admin", name: "API key admin", email: null };
    vi.stubGlobal("fetch", vi.fn(async () => json(200, key)));
    render(
      <AuthProvider>
        <Shell />
      </AuthProvider>,
    );
    expect(await screen.findByText("Signed in as API key admin")).toBeInTheDocument();
  });

  it("does not sign out on a failed approval-link or sign-in call", () => {
    const heard = vi.fn();
    window.addEventListener(SIGNED_OUT_EVENT, heard);
    vi.stubGlobal("fetch", vi.fn(async () => json(401, UNAUTHORISED)));
    return Promise.allSettled([api.inspectLink("x"), api.login("a@b.c", "x")]).then(() => {
      window.removeEventListener(SIGNED_OUT_EVENT, heard);
      expect(heard).not.toHaveBeenCalled();
    });
  });
});

const EVENT: AuditEvent = {
  id: "aud_1",
  at: 0,
  actor_kind: "user",
  actor_id: "usr_1",
  actor_name: "Dana Lee",
  action: "rule.confirm",
  method: "POST",
  route: "/v1/tenants/{tenant_id}/instructions/{instruction_id}/confirm",
  tenant_id: "acme",
  target: "ins_1",
  status: 200,
  outcome: "success",
  request_id: "req_1",
};

describe("audit sentences", () => {
  it("says who did what, and phrases refusals as attempts", () => {
    expect(describeEvent(EVENT)).toEqual({ actor: "Dana Lee", verb: "confirmed a rule", category: "rules" });
    expect(describeEvent({ ...EVENT, outcome: "denied", status: 403 }).verb).toBe("tried to confirm a rule");
    const failedLogin = {
      ...EVENT,
      action: "auth.login",
      actor_kind: "anonymous" as const,
      actor_id: null,
      actor_name: "x@example.com",
      outcome: "denied" as const,
    };
    expect(describeEvent(failedLogin)).toMatchObject({
      actor: "Someone using x@example.com",
      verb: "failed to sign in",
    });
    expect(describeEvent({ ...EVENT, action: "brand.new" }).verb).toBe(`called POST ${EVENT.route}`);
  });
});

const USERS: ConsoleUser[] = [
  {
    id: "usr_1",
    email: "dana@example.com",
    name: "Dana Lee",
    role: "admin",
    tenants: null,
    disabled: false,
    created_at: 0,
    updated_at: 0,
    last_login_at: Date.now(),
  },
  {
    id: "usr_2",
    email: "ops@example.com",
    name: "Ops",
    role: "viewer",
    tenants: ["acme"],
    disabled: true,
    created_at: 0,
    updated_at: 0,
    last_login_at: null,
  },
];

describe("Users page", () => {
  it("lists users with role, access and status for an admin with every tenant", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (url === "/v1/users" ? json(200, USERS) : json(200, []))),
    );
    render(
      <MemoryRouter>
        <TestAuth me={DANA}>
          <Users />
        </TestAuth>
      </MemoryRouter>,
    );
    expect(await screen.findByText("ops@example.com")).toBeInTheDocument();
    expect(screen.getByText("you")).toBeInTheDocument();
    expect(screen.getByText("All tenants")).toBeInTheDocument();
    expect(screen.getByText("Disabled", { selector: ".status-dot" })).toBeInTheDocument();
    expect(screen.getByText("never")).toBeInTheDocument();
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: /Invite user/ }));
    });
    expect(await screen.findByRole("dialog", { name: "Invite a user" })).toBeInTheDocument();
  });

  it("explains that managing users needs an admin with every tenant", async () => {
    const fetchMock = vi.fn(async (_url: string) => json(200, []));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <TestAuth me={{ ...DANA, tenants: ["acme"] }}>
          <Users />
        </TestAuth>
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("Managing users needs an admin with every tenant."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === "/v1/users")).toBe(false),
    );
  });
});

describe("device names", () => {
  it("names the browser and the system from a user agent", async () => {
    const { deviceName } = await import("./components/AccountMenu");
    const edge =
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0";
    expect(deviceName(edge)).toEqual({ label: "Edge on Windows", mobile: false });
    const iphone =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
    expect(deviceName(iphone)).toEqual({ label: "Safari on iOS", mobile: true });
    expect(deviceName("python-httpx/0.28")).toEqual({ label: "A script", mobile: false });
    expect(deviceName(null).label).toBe("Unknown device");
  });
});
