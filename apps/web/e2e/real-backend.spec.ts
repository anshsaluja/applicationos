import { expect, test } from "@playwright/test";

// This test deliberately uses the real Compose API and PostgreSQL. It must
// never run against a production API or with a real application document.
test("real backend persists uploaded instructions and displays provenance", async ({ page }) => {
  test.skip(process.env.APPLICATIONOS_REAL_E2E !== "1", "Requires disposable Compose stack");
  if (process.env.APPLICATIONOS_REAL_E2E === "1" && process.env.CI && !process.env.APPLICATIONOS_E2E_REVIEW_TOKEN) {
    throw new Error("Compose E2E reviewer credential missing; fail closed rather than silently skipping approval coverage");
  }
  const instructions = "Provide an official transcript for the synthetic applicant.";
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "synthetic-instructions.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(instructions),
  });
  await page.getByRole("button", { name: "Extract and save requirements" }).click();
  await expect(page.getByRole("heading", { name: /Saved requirements \([1-9][0-9]*\)/ })).toBeVisible();
  await expect(page.getByText("Source: synthetic-instructions.txt").first()).toBeVisible();
  await expect(page.locator("blockquote").filter({ hasText: instructions }).first()).toBeVisible();
  await expect(page.getByText(/Instruction excerpts are source provenance/)).toBeVisible();
  await expect(page.getByText(/Satisfaction evidence: 0 item\(s\)\./).first()).toBeVisible();
  await expect(page.locator("p[role=alert]")).toHaveCount(0);
});

test("real backend enforces human rejection before execution", async ({ page }) => {
  test.skip(process.env.APPLICATIONOS_REAL_E2E !== "1", "Requires disposable Compose stack");
  if (process.env.APPLICATIONOS_REAL_E2E === "1" && process.env.CI && !process.env.APPLICATIONOS_E2E_REVIEW_TOKEN) {
    throw new Error("Compose E2E reviewer credential missing; fail closed rather than silently skipping approval coverage");
  }
  const token = process.env.APPLICATIONOS_E2E_REVIEW_TOKEN;
  if (!token) throw new Error("Real-backend E2E requires a disposable reviewer credential; refusing to skip approval tests");

  const actionId = crypto.randomUUID();
  await page.goto("/");
  await page.getByPlaceholder("Action UUID").fill(actionId);
  await page.getByPlaceholder("Unique request key").fill(`browser-rejection-${actionId}`);
  await page.getByRole("button", { name: "Create checkpoint" }).click();
  await expect(page.getByText("Workflow checkpoint saved. No action has been executed.")).toBeVisible();
  await expect(page.getByText("Status: pending")).toBeVisible();

  await page.getByRole("button", { name: "Request human review" }).click();
  await expect(page.getByRole("heading", { name: "Operator review" })).toBeVisible();
  // A forged reviewer credential must fail closed without changing the checkpoint.
  await page.getByLabel("Operator token (local development only)").fill("invalid-synthetic-review-token");
  await page.getByLabel("Decision").selectOption("approved");
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(page.locator("p[role=alert]")).toContainText("403");
  await expect(page.getByText("Status: awaiting approval")).toBeVisible();
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("Status: awaiting approval")).toBeVisible();

  // A valid reviewer can subsequently reject the same persisted checkpoint.
  await page.getByLabel("Operator token (local development only)").fill(token!);
  await page.getByLabel("Decision").selectOption("rejected");
  await page.getByLabel("Reason (required)").fill("Synthetic application requires manual correction");
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(page.getByText("Rejected. Workflow execution remains blocked.")).toBeVisible();
  await expect(page.getByText("Status: failed")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operator review" })).toHaveCount(0);
  await page.reload();
  await page.getByPlaceholder("Action UUID").fill(actionId);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("Status: failed")).toBeVisible();
  await expect(page.getByRole("button", { name: "Request human review" })).toBeDisabled();

  // A terminal rejection must not be reversible by replaying an approval.
  const replay = await page.request.post(`http://127.0.0.1:8000/v1/workflows/${actionId}/decision`, {
    headers: { "X-Review-Token": token! },
    data: { decision: "approved", reason: "Attempted reversal after rejection" },
  });
  expect(replay.status()).toBe(409);
  const persisted = await page.request.get(`http://127.0.0.1:8000/v1/workflows/${actionId}`);
  expect(persisted.ok()).toBeTruthy();
  expect((await persisted.json()).status).toBe("failed");
});


test("real backend persists authorized approval without executing an external action", async ({ page }) => {
  test.skip(process.env.APPLICATIONOS_REAL_E2E !== "1", "Requires disposable Compose stack");
  if (process.env.APPLICATIONOS_REAL_E2E === "1" && process.env.CI && !process.env.APPLICATIONOS_E2E_REVIEW_TOKEN) {
    throw new Error("Compose E2E reviewer credential missing; fail closed rather than silently skipping approval coverage");
  }
  const token = process.env.APPLICATIONOS_E2E_REVIEW_TOKEN;
  if (!token) throw new Error("Real-backend E2E requires a disposable reviewer credential; refusing to skip approval tests");

  const actionId = crypto.randomUUID();
  const key = `browser-approval-${actionId}`;
  await page.goto("/");
  await page.getByPlaceholder("Action UUID").fill(actionId);
  await page.getByPlaceholder("Unique request key").fill(key);
  await page.getByRole("button", { name: "Create checkpoint" }).click();
  await expect(page.getByText("Status: pending")).toBeVisible();
  await page.getByRole("button", { name: "Request human review" }).click();
  await expect(page.getByText("Status: awaiting approval")).toBeVisible();

  await page.getByLabel("Operator token (local development only)").fill(token!);
  await page.getByLabel("Decision").selectOption("approved");
  await page.getByLabel("Reason (optional)").fill("Synthetic reviewer verified the local checkpoint");
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(page.getByText("Approved and ready. No external action has been executed.")).toBeVisible();
  await expect(page.getByText("Status: ready")).toBeVisible();
  await expect(page.getByText(`Idempotency key: ${key}`)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operator review" })).toHaveCount(0);

  // Reload from PostgreSQL, not the browser's in-memory state.
  await page.reload();
  await page.getByPlaceholder("Action UUID").fill(actionId);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("Status: ready")).toBeVisible();
  await expect(page.getByText(`Idempotency key: ${key}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Request human review" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Operator review" })).toHaveCount(0);

  // Approval replay and conflicting rejection both fail closed after persistence.
  for (const decision of ["approved", "rejected"]) {
    const replay = await page.request.post(`http://127.0.0.1:8000/v1/workflows/${actionId}/decision`, {
      headers: { "X-Review-Token": token! },
      data: { decision, reason: "Duplicate terminal decision" },
    });
    expect(replay.status()).toBe(409);
  }
  const persisted = await page.request.get(`http://127.0.0.1:8000/v1/workflows/${actionId}`);
  expect(persisted.ok()).toBeTruthy();
  expect((await persisted.json()).status).toBe("ready");
});
