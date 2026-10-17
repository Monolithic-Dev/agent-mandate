import { expect, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS;

test("an admin adds an alert, pauses it and removes it; private addresses are refused", async ({
  page,
}) => {
  await page.goto("/tenants/demo?tab=alerts");
  await expect(page.getByRole("tab", { name: /Alerts/ })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Add alert" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add an alert" });
  await dialog.getByLabel("Name").fill("E2E channel");

  // The API refuses an address inside its own network (no SSRF).
  await dialog.getByLabel("URL").fill("https://169.254.169.254/latest/meta-data");
  await dialog.getByRole("button", { name: "Add alert" }).click();
  await expect(dialog.getByRole("alert")).toContainText("private or local address");

  await dialog.getByLabel("URL").fill("https://93.184.216.34/hooks/e2e-test-1234");
  await dialog.getByRole("button", { name: "Add alert" }).click();
  const card = page.locator(".hook-card", { hasText: "E2E channel" });
  await expect(card).toContainText("https://93.184.216.34/…1234");
  await expect(card).toContainText("Waiting for the first held action");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/alerts.png`, fullPage: true });

  await card.getByRole("button", { name: "Pause" }).click();
  await expect(card).toContainText("Paused");
  await card.getByRole("button", { name: "Remove E2E channel" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove alert" }).click();
  await expect(card).toHaveCount(0);
});

test("the activity tab charts the demo tenant's decisions", async ({ page }) => {
  await page.goto("/tenants/demo?tab=activity");
  await expect(page.getByRole("img", { name: /Decisions per hour, by outcome/ })).toBeVisible();
  await expect(page.locator(".legend")).toContainText("Allowed");
  await page.locator(".bar-hit").last().hover();
  await expect(page.locator(".chart-tooltip")).toContainText("Needs approval");
  if (SHOTS) {
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/activity.png`, fullPage: true });
  }
});

test("the activity chart in the dark theme", async ({ page }) => {
  test.skip(!SHOTS, "only for the visual check");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/tenants/demo?tab=activity");
  await page.locator(".bar-hit").last().hover();
  await page.waitForTimeout(600);
  await page.locator(".chart-card").screenshot({ path: `${SHOTS}/activity-dark.png` });
});
