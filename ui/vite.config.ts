import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

// The API key never reaches the browser: the dev server's proxy adds it to every /v1
// request. It reads MANDATE_API_KEY (and optionally MANDATE_API_URL) from the repository's
// .env or the environment. Do not prefix it with VITE_, which would put it in the bundle.
// MANDATE_UI_AUTH=login sends no key, so the console asks people to sign in, as in production.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const target = env.MANDATE_API_URL || "http://127.0.0.1:8000";
  const login = env.MANDATE_UI_AUTH === "login";
  const key = login ? "" : env.MANDATE_UI_KEY || env.MANDATE_API_KEY || "";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/v1": { target, changeOrigin: true, headers: key ? { "X-Mandate-Key": key } : {} },
      },
    },
    test: {
      environment: "jsdom",
      include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright's
      setupFiles: ["./src/test/setup.ts"],
      testTimeout: 20_000,
    },
  };
});
