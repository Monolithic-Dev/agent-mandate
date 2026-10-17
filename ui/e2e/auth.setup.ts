import { expect, test as setup } from "@playwright/test";

import { STATE } from "../playwright.config";

// Sign in once for every test, when the console asks for it; otherwise save an empty state.
setup("sign in", async ({ page }) => {
  await page.goto("/");
  const email = process.env.E2E_EMAIL;
  const password = process.env.E2E_PASSWORD;
  const form = page.getByRole("heading", { name: "Sign in to the console" });
  const shell = page.getByRole("button", { name: "Account" });
  await expect(form.or(shell)).toBeVisible();
  if (await form.isVisible()) {
    if (!email || !password) throw new Error("the console asks to sign in: set E2E_EMAIL and E2E_PASSWORD");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(shell).toBeVisible();
  }
  await page.context().storageState({ path: STATE });
});
