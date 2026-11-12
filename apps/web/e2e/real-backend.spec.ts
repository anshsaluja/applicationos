import { expect, test } from "@playwright/test";

// This test deliberately uses the real Compose API and PostgreSQL. It must
// never run against a production API or with a real application document.
test("real backend persists uploaded instructions and displays provenance", async ({ page }) => {
  test.skip(process.env.APPLICATIONOS_REAL_E2E !== "1", "Requires disposable Compose stack");
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
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("real backend enforces human rejection before execution", async ({ page }) => {
  test.skip(process.env.APPLICATIONOS_REAL_E2E !== "1", "Requires disposable Compose stack");
  const token = process.env.APPLICATIONOS_E2E_REVIEW_TOKEN;
  test.skip(!token, "Requires disposable CI reviewer credential");

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
  await expect(page.getByRole("alert")).toContainText("401");
  await expect(page.getByText("Status: awaiting approval")).toBeVisible();
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("Status: awaiting approval")).toBeVisible();

  // A valid reviewer can subsequently reject the same persisted checkpoint.
  await page.getByLabel("Operator token (local development only)").fill(token!);
  await page.getByLabel("Decision").selectOption("rejected");
  await page.getByLabel("Reason (required)").fill("Synthetic application requires manual correction");
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(page.getByText("Rejected. Workflow execution remains blocked.")).toBeVisible();
  await expect(page.getByText("Status: rejected")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operator review" })).toHaveCount(0);
  await page.reload();
  await page.getByPlaceholder("Action UUID").fill(actionId);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("Status: rejected")).toBeVisible();
  await expect(page.getByRole("button", { name: "Request human review" })).toBeDisabled();
});
