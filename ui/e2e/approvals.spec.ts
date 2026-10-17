import { expect, type APIRequestContext, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS;
const S1 = "You may read and archive my email, but confirm with me before deleting anything.";

// A tenant of its own (through the console's proxy, which adds the key), with two email
// deletions held for the owner, so this test never races the demo tenant's resets.
async function tenantWithTwoHeldDeletes(request: APIRequestContext): Promise<string> {
  const tid = `e2e_${Date.now().toString(36)}`;
  const base = `/v1/tenants/${tid}`;
  const post = async (path: string, data: unknown) => {
    const response = await request.post(path, { data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  await post("/v1/tenants", { tenant_id: tid, name: "Approvals e2e" });
  const owner = await post(`${base}/principals`, { name: "Dana", role: "owner" });
  const agent = await post(`${base}/agents`, { name: "assistant", kind: "primary" });
  const said = await post(`${base}/utterances`, {
    principal_id: owner.id,
    text: S1,
    channel: "owner_direct",
  });
  for (const item of said.instructions) {
    if (item.needs_confirmation) {
      await post(`${base}/instructions/${item.instruction.id}/confirm`, { by: owner.id });
    }
  }
  for (const message_id of ["m-1", "m-2"]) {
    const held = await post(`${base}/tool-calls`, {
      agent_id: agent.id,
      tool: "email_delete",
      args: { message_id },
    });
    expect(held.status).toBe("confirmation_required");
  }
  return tid;
}

async function holdDelete(request: APIRequestContext, tid: string, message_id: string) {
  const agents = await (await request.get(`/v1/tenants/${tid}/agents`)).json();
  const held = await request.post(`/v1/tenants/${tid}/tool-calls`, {
    data: { agent_id: agents[0].id, tool: "email_delete", args: { message_id } },
  });
  expect((await held.json()).status).toBe("confirmation_required");
}

test("the owner approves one held action in the console and another through a link", async ({
  page,
  request,
}) => {
  const tid = await tenantWithTwoHeldDeletes(request);
  try {
    await page.goto(`/tenants/${tid}`);
    await expect(page.getByRole("tab", { name: /Waiting for approval/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const first = 'email_delete(message_id="m-1")';
    const second = 'email_delete(message_id="m-2")';
    await expect(page.getByRole("button", { name: `Approve ${first}` })).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/approvals.png`, fullPage: true });

    await page.getByRole("button", { name: `Approve ${first}` }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText(first);
    await dialog.getByRole("button", { name: "Approve and run" }).click();
    await expect(page.getByText(`Approved: ${first} ran.`)).toBeVisible();
    await expect(page.getByRole("button", { name: `Approve ${first}` })).toHaveCount(0);

    await page.getByRole("button", { name: `Make an approval link for ${second}` }).click();
    const url = await page.getByRole("textbox", { name: /single use/ }).inputValue();
    expect(url).toMatch(/\/approve#apl1\./);

    await page.goto(url);
    await expect(page.getByText(/wants to run/)).toContainText(second);
    await expect(page.getByText(/Needs approval/)).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/approve-link.png`, fullPage: true });
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByRole("status")).toHaveText("Approved. The action ran.");

    await page.reload();
    await expect(page.getByText(/already been approved or declined/)).toBeVisible();
    await page.goto(`/tenants/${tid}`);
    await expect(page.getByText("Nothing is waiting for approval.")).toBeVisible();
  } finally {
    await request.delete(`/v1/tenants/${tid}`);
  }
});

test("a new held action appears on an open tenant page without a reload", async ({
  page,
  request,
}) => {
  const tid = await tenantWithTwoHeldDeletes(request);
  try {
    await page.goto(`/tenants/${tid}`);
    await expect(page.locator("h1 .live")).toHaveText(/live/);
    // An agent acts while the owner is looking at the page.
    await holdDelete(request, tid, "m-3");
    const third = 'email_delete(message_id="m-3")';
    await expect(page.getByRole("button", { name: `Approve ${third}` })).toBeVisible();
    await expect(page.getByText("A new action is waiting for approval.")).toBeVisible();
    await page.getByRole("tab", { name: /Decisions/ }).click();
    await expect(page.getByRole("link", { name: "email.delete inbox/m-3" })).toBeVisible();
  } finally {
    await request.delete(`/v1/tenants/${tid}`);
  }
});
