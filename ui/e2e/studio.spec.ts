import { expect, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS;

// A tenant of its own with an owner, an agent and one refund that nobody allowed, so the
// preview has a recent request to re-check and the test never races the demo's resets.
async function tenant(request: import("@playwright/test").APIRequestContext): Promise<string> {
  const tid = `e2e_studio_${Date.now().toString(36)}`;
  const post = async (path: string, data: unknown) => {
    const response = await request.post(path, { data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  await post("/v1/tenants", { tenant_id: tid, name: "Studio e2e" });
  await post(`/v1/tenants/${tid}/principals`, { name: "Dana", role: "owner" });
  const agent = await post(`/v1/tenants/${tid}/agents`, { name: "assistant", kind: "primary" });
  await post(`/v1/tenants/${tid}/check`, {
    agent_id: agent.id,
    action_type: "refund.issue",
    resource: "order/7",
    args: { amount: 300 },
  });
  return tid;
}

test("the studio previews a sentence, saves it, and the simulator then allows the refund", async ({
  page,
  request,
}) => {
  const tid = await tenant(request);
  await page.goto(`/tenants/${tid}`);
  await page.getByRole("link", { name: "Rule studio" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`Rules for ${tid}`);

  // Before: the simulator refuses a refund nobody allowed.
  await page.getByLabel("Amount ($)").fill("300");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByRole("status").filter({ hasText: "no rule allows it" })).toBeVisible();

  await page
    .getByLabel("What the owner says")
    .fill("For the next 2 hours, you may issue refunds up to $1,000. Be nice to people.");
  await expect(page.getByText("This would make 1 rule")).toBeVisible();
  await expect(page.getByText("issue refunds up to $1,000", { exact: true })).toBeVisible();
  await expect(page.locator(".rule-preview").getByText("for 2 hours")).toBeVisible();
  await expect(page.getByText("“Be nice to people”")).toBeVisible();
  await expect(page.getByText("Would change 1 of 1 recent request")).toBeVisible();
  if (SHOTS) {
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/studio.png`, fullPage: true });
  }

  await page.getByRole("button", { name: "Save and confirm as the owner" }).click();
  await expect(page.getByLabel("What the owner says")).toHaveValue("");

  // After: the same check is allowed, and the rule shows its expiry.
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByRole("status").filter({ hasText: "a rule allows it" })).toBeVisible();
  await page.goto(`/tenants/${tid}?tab=rules`);
  await expect(page.getByText(/expires in 2 hours/)).toBeVisible();

  await request.delete(`/v1/tenants/${tid}`);
});
