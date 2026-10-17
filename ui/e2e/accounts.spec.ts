import { expect, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS;
const signInMode = !!process.env.E2E_EMAIL;

test.describe("console accounts", () => {
  test.skip(!signInMode, "the console signs in with a key here; set E2E_EMAIL to run these");

  test("an admin invites a viewer, who signs in read-only, and the audit log shows it all", async ({
    page,
    browser,
  }) => {
    const email = `viewer.${Date.now().toString(36)}@example.com`;

    await page.goto("/admin/users");
    await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
    await page.getByRole("button", { name: "Invite user" }).click();
    const invite = page.getByRole("dialog", { name: "Invite a user" });
    await invite.getByLabel("Name").fill("Vic Viewer");
    await invite.getByLabel("Email").fill(email);
    await invite.getByText("Viewer", { exact: true }).click();
    await invite.getByRole("button", { name: "Create user" }).click();
    const created = page.getByRole("dialog", { name: "User created" });
    await expect(created).toBeVisible();
    const password = (await created.locator(".copy-row code").nth(1).textContent()) ?? "";
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/users-invite.png` });
    await created.getByRole("button", { name: "Done" }).click();
    await expect(page.getByRole("cell", { name: new RegExp(email) })).toBeVisible();

    // The viewer, in a browser of their own.
    const viewerContext = await browser.newContext({ storageState: undefined });
    const viewer = await viewerContext.newPage();
    await viewer.goto("/");
    await expect(viewer.getByRole("heading", { name: "Sign in to the console" })).toBeVisible();
    if (SHOTS) {
      await viewer.waitForTimeout(2500); // let the entrance animation finish
      await viewer.screenshot({ path: `${SHOTS}/sign-in.png` });
    }
    await viewer.getByLabel("Email").fill(email);
    await viewer.getByLabel("Password", { exact: true }).fill("not the password");
    await viewer.getByRole("button", { name: "Sign in" }).click();
    await expect(viewer.getByRole("alert")).toContainText("do not match");
    await viewer.getByLabel("Password", { exact: true }).fill(password);
    await viewer.getByRole("button", { name: "Sign in" }).click();
    await expect(viewer.getByRole("button", { name: "Account" })).toContainText("Vic Viewer");
    await expect(viewer.getByRole("button", { name: "Run" })).toBeDisabled();
    await expect(viewer.getByText("read-only role")).toBeVisible();
    await expect(viewer.getByRole("link", { name: "Audit log" })).toHaveCount(0);

    // Signing out ends the session for good.
    await viewer.getByRole("button", { name: "Account" }).click();
    await viewer.getByRole("menuitem", { name: "Sign out", exact: true }).click();
    await expect(viewer.getByRole("heading", { name: "Sign in to the console" })).toBeVisible();
    await viewerContext.close();

    // The admin sees the story in the audit log.
    await page.goto("/admin/audit");
    await expect(page.getByRole("heading", { level: 1, name: "Audit log" })).toBeVisible();
    await expect(page.getByText("Vic Viewer signed out").first()).toBeVisible();
    await expect(page.getByText("Vic Viewer signed in").first()).toBeVisible();
    await expect(page.getByText(`Someone using ${email} failed to sign in`).first()).toBeVisible();
    await expect(page.getByText(/created a user/).first()).toBeVisible();
    await page.getByText("Vic Viewer signed in").first().click();
    await expect(page.getByText("/v1/auth/login").first()).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/audit.png`, fullPage: true });
  });

  test("the account menu lists where you are signed in", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Account" }).click();
    await page.getByRole("menuitem", { name: "Where you're signed in" }).click();
    const dialog = page.getByRole("dialog", { name: "Where you're signed in" });
    await expect(dialog.getByText("this browser")).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/sessions.png` });
  });
});
