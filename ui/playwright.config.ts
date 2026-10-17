import { defineConfig } from "@playwright/test";

// Smoke tests against a running stack (API, FalkorDB and the dev server or the ui image):
//   E2E_BASE_URL=http://localhost:5173 npm run e2e
// They use an installed Chrome or Edge (E2E_CHANNEL, default msedge on Windows, chrome
// elsewhere), so no browser download is needed. Not part of `npm test`.
//
// When the console asks people to sign in (the production default), set E2E_EMAIL and
// E2E_PASSWORD to an admin user: the setup project signs in once and every test reuses that
// session. With a console key on the server there is nothing to sign in to and they are unused.
export const STATE = "e2e/.auth/state.json";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // One at a time: the tests share one stack, and the demo's run resets the demo tenant that
  // others read. (Tests that change things make tenants of their own.)
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    channel: process.env.E2E_CHANNEL ?? (process.platform === "win32" ? "msedge" : "chrome"),
    viewport: { width: 1366, height: 900 },
    // What the console sends on every call; the API needs it for changes made with a session.
    extraHTTPHeaders: { "X-Mandate-Client": "console" },
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "console",
      testIgnore: /auth\.setup\.ts/,
      dependencies: ["setup"],
      use: { storageState: STATE },
    },
  ],
  reporter: "list",
});
