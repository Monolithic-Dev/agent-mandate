import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Every console page, audited by axe against WCAG 2.2 AA in both themes, and checked at a
// phone's width for sideways scrolling. A violation fails the run with what axe found and
// where, so the console stays accessible as it grows rather than being audited once.

const SHOTS = process.env.E2E_SCREENSHOTS;
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function settle(page: Page) {
  await expect(page.locator("h1").first()).toBeVisible();
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 15_000 });
  await animationsDone(page);
}

/** Fades still run under reduced motion (only movement stops), and a half-faded word is
 *  measured at half its contrast: wait until nothing is mid-fade before auditing. */
async function animationsDone(page: Page) {
  await page
    .waitForFunction(
      () =>
        document.getAnimations().every((a) => a.playState !== "running") &&
        [...document.querySelectorAll<HTMLElement>("[style*='opacity']")].every((el) => {
          const opacity = parseFloat(el.style.opacity);
          return Number.isNaN(opacity) || opacity === 0 || opacity === 1;
        }),
      undefined,
      { timeout: 10_000 },
    )
    .catch(() => undefined); // a page with a looping animation: audit it after a fixed wait
  await page.waitForTimeout(150);
}

async function audit(page: Page, what: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const report = violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help}\n` +
      v.nodes
        .slice(0, 5)
        .map(
          (n) =>
            `    ${n.target.join(" ")}\n      ${n.failureSummary?.split("\n").join("\n      ")}`,
        )
        .join("\n"),
  );
  expect(report, `${what}\n${report.join("\n")}`).toEqual([]);
}

async function pages(page: Page): Promise<{ name: string; path: string }[]> {
  const decisions = await (await page.request.get("/v1/tenants/demo/decisions")).json();
  const rules = await (await page.request.get("/v1/tenants/demo/instructions")).json();
  return [
    { name: "demo", path: "/" },
    { name: "tenants", path: "/tenants" },
    { name: "tenant-approvals", path: "/tenants/demo" },
    { name: "tenant-rules", path: "/tenants/demo?tab=rules" },
    { name: "tenant-decisions", path: "/tenants/demo?tab=decisions" },
    { name: "tenant-activity", path: "/tenants/demo?tab=activity" },
    { name: "tenant-graph", path: "/tenants/demo?tab=graph" },
    { name: "tenant-alerts", path: "/tenants/demo?tab=alerts" },
    { name: "decision", path: `/tenants/demo/decisions/${decisions[0].decision.id}` },
    { name: "rule", path: `/tenants/demo/instructions/${rules[0].instruction.id}` },
    { name: "studio", path: "/tenants/demo/studio" },
    { name: "eval", path: "/eval" },
    { name: "users", path: "/admin/users" },
    { name: "audit", path: "/admin/audit" },
  ];
}

for (const scheme of ["light", "dark"] as const) {
  test(`every page passes WCAG 2.2 AA in the ${scheme} theme`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    for (const { name, path } of await pages(page)) {
      await page.goto(path);
      await settle(page);
      await audit(page, `${name} (${path}), ${scheme}`);
    }
  });
}

test("every page fits a phone, and the menu opens in a drawer", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const { name, path } of await pages(page)) {
    await page.goto(path);
    await settle(page);
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${name} (${path}) scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(0);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/phone-${name}.png`, fullPage: true });
  }

  await page.getByRole("button", { name: "Open the menu" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu).toBeVisible();
  await animationsDone(page);
  await audit(page, "the menu drawer");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/phone-menu.png` });
  await menu.getByRole("link", { name: "Tenants" }).click();
  await expect(menu).toBeHidden();
  await expect(page).toHaveURL(/\/tenants$/);
});

test.describe("without a session", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the sign-in page passes WCAG 2.2 AA", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Sign in/ })).toBeVisible();
    await animationsDone(page);
    await audit(page, "sign-in");
  });
});
