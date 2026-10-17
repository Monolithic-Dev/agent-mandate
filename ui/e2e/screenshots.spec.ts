import { expect, type Page, test } from "@playwright/test";

// Regenerates the images the README shows, from a running, seeded stack:
//   README_SHOTS=../docs/images E2E_BASE_URL=http://127.0.0.1:8180 E2E_EMAIL=... \
//     E2E_PASSWORD=... npx playwright test screenshots
// Skipped unless README_SHOTS is set, so a normal run never rewrites them.

const DIR = process.env.README_SHOTS;
test.skip(!DIR, "set README_SHOTS to the folder the images go in");
test.describe.configure({ mode: "serial" });

async function settle(page: Page) {
  await expect(page.locator("h1").first()).toBeVisible();
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 15_000 });
  await page.waitForTimeout(1200); // entrance animations and the graph layout
}

async function shot(page: Page, name: string, fullPage = false) {
  await page.screenshot({ path: `${DIR}/${name}.png`, fullPage });
}

test.use({ viewport: { width: 1360, height: 860 }, deviceScaleFactor: 1 });

test("the demo, side by side", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Run" }).click();
  await page.getByRole("button", { name: "Show all" }).click();
  await expect(page.getByTestId("count-mandate")).toHaveText("0");
  await page.waitForTimeout(1500);
  await page.setViewportSize({ width: 1360, height: 1400 }); // the page, without the floating bar mid-way
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await shot(page, "demo");
});

test("a tenant, waiting for approval", async ({ page }) => {
  await page.goto("/tenants/demo");
  await settle(page);
  await shot(page, "tenant");
});

test("the rule studio previews a sentence", async ({ page }) => {
  await page.goto("/tenants/demo/studio");
  await page.setViewportSize({ width: 1360, height: 1160 });
  await settle(page);
  await page
    .getByLabel("What the owner says")
    .fill(
      "For the next 2 hours, you may issue refunds up to $1,000, but ask me before sending anything.",
    );
  await expect(page.getByText(/This would make \d rules?/)).toBeVisible();
  await page.waitForTimeout(1200);
  await shot(page, "studio");
});

test("a decision explained", async ({ page }) => {
  const decisions = await (await page.request.get("/v1/tenants/demo/decisions")).json();
  const allowed = decisions.find(
    (d: { decision: { result: string } }) => d.decision.result === "allow",
  );
  await page.setViewportSize({ width: 1360, height: 1300 });
  await page.goto(`/tenants/demo/decisions/${(allowed ?? decisions[0]).decision.id}`);
  await settle(page);
  await shot(page, "decision");
});

test("the graph explorer traces a decision", async ({ page }) => {
  const decisions = await (await page.request.get("/v1/tenants/demo/decisions")).json();
  const allowed = decisions.find(
    (d: { decision: { result: string } }) => d.decision.result === "allow",
  );
  await page.goto(`/tenants/demo?tab=graph&node=${(allowed ?? decisions[0]).decision.id}&trace=1`);
  await page.setViewportSize({ width: 1360, height: 1180 });
  await settle(page);
  await page.waitForTimeout(2500); // the layout and the fit onto the lineage
  await shot(page, "explorer");
});

test("the activity overview", async ({ page }) => {
  await page.goto("/tenants/demo?tab=activity");
  await page.setViewportSize({ width: 1360, height: 1280 });
  await settle(page);
  await page.locator(".bar-hit").last().hover();
  await shot(page, "activity");
});

test("the activity overview in dark", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/tenants/demo?tab=activity");
  await settle(page);
  await shot(page, "activity-dark");
});

test("the audit log", async ({ page }) => {
  await page.goto("/admin/audit");
  await settle(page);
  await shot(page, "audit");
});

test("users", async ({ page }) => {
  await page.goto("/admin/users");
  await settle(page);
  await shot(page, "users");
});

test("on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/tenants/demo");
  await settle(page);
  await shot(page, "phone-approvals");
  await page.getByRole("button", { name: "Open the menu" }).click();
  await expect(page.getByRole("dialog", { name: "Menu" })).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "phone-menu");
});
