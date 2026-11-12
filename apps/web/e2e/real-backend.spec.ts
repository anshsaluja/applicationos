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
