import { expect, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS;

// A tenant of its own: the owner allows reading email, the agent reads one message, and that
// decision is traced back through the rule to what the owner said.
async function tenant(request: import("@playwright/test").APIRequestContext): Promise<string> {
  const tid = `e2e_graph_${Date.now().toString(36)}`;
  const post = async (path: string, data: unknown) => {
    const response = await request.post(path, { data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  await post("/v1/tenants", { tenant_id: tid, name: "Explorer e2e" });
  const owner = await post(`/v1/tenants/${tid}/principals`, { name: "Dana", role: "owner" });
  const agent = await post(`/v1/tenants/${tid}/agents`, { name: "assistant", kind: "primary" });
  await post(`/v1/tenants/${tid}/utterances`, {
    principal_id: owner.id,
    text: "You may read my email.",
    channel: "owner_direct",
  });
  await post(`/v1/tenants/${tid}/check`, {
    agent_id: agent.id,
    action_type: "email.read",
    resource: "inbox/m-1",
  });
  return tid;
}

test("the explorer finds a decision and traces it back to what the owner said", async ({
  page,
  request,
}) => {
  const tid = await tenant(request);
  await page.goto(`/tenants/${tid}?tab=graph`);
  const inspector = page.getByRole("complementary", { name: "Selected node" });
  await expect(inspector.getByText("Pick a node")).toBeVisible();

  await page.keyboard.press("/");
  const search = page.getByRole("combobox", { name: "Find a node in the graph" });
  await expect(search).toBeFocused();
  await search.fill("authorized");
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(inspector.getByRole("heading", { name: /ALLOW: authorized/ })).toBeVisible();

  await inspector.getByRole("button", { name: "Trace lineage" }).click();
  const cameFrom = inspector.getByRole("region", { name: "Came from" });
  await expect(cameFrom.getByText("Dana (owner)")).toBeVisible();
  await expect(cameFrom.getByText("allow: You may read my email", { exact: true })).toBeVisible();
  await expect(cameFrom.getByText("You may read my email.", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/node=dec_.*trace=1|trace=1.*node=dec_/);
  if (SHOTS) {
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${SHOTS}/explorer.png`, fullPage: true });
  }

  // Walking up the lineage: the owner, and everything their words became.
  await cameFrom.getByRole("button", { name: /Dana \(owner\)/ }).click();
  await expect(inspector.getByRole("heading", { name: "Dana (owner)" })).toBeVisible();
  const ledTo = inspector.getByRole("region", { name: "Led to" });
  await expect(ledTo.getByText(/ALLOW: authorized/)).toBeVisible();

  // The traced view is a link: opened fresh, it shows the same.
  await page.reload();
  await expect(inspector.getByRole("heading", { name: "Dana (owner)" })).toBeVisible();
  await expect(inspector.getByRole("button", { name: "Stop tracing" })).toBeVisible();
});

test("on a phone the explorer stacks, details first", async ({ page, request }) => {
  const tid = await tenant(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/tenants/${tid}?tab=graph`);
  const search = page.getByRole("combobox", { name: "Find a node in the graph" });
  await search.fill("Dana");
  await page.getByRole("option").first().click();
  const inspector = page.getByRole("complementary", { name: "Selected node" });
  await expect(inspector.getByRole("heading", { name: "Dana (owner)" })).toBeVisible();
  // Nothing scrolls sideways.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  if (SHOTS) {
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS}/explorer-phone.png`, fullPage: true });
  }
});
