import { expect, test } from "@playwright/test";

const DOCUMENT_ID = "11111111-1111-4111-8111-111111111111";
const WORKSPACE_ID = "22222222-2222-4222-8222-222222222222";
const REQUIREMENT_ID = "33333333-3333-4333-8333-333333333333";

test("document upload shows instruction provenance without claiming satisfaction", async ({ page }) => {
  await page.route("**/v1/documents", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      id: DOCUMENT_ID, filename: "instructions.txt", sha256: "demo", text: "Provide a transcript."
    }) });
  });
  await page.route(`**/v1/documents/${DOCUMENT_ID}/requirements/persist`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      workspace_id: WORKSPACE_ID, requirements: [{
        id: REQUIREMENT_ID, title: "Transcript", description: "Provide a transcript.",
        status: "missing", evidence: []
      }]
    }) });
  });
  await page.route(`**/v1/documents/${DOCUMENT_ID}/requirement-sources`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{
      requirement_id: REQUIREMENT_ID, instruction_excerpt: "Provide a transcript.",
      source_document_id: DOCUMENT_ID, source_label: "instructions.txt",
      status: "missing", satisfaction_evidence: []
    }]) });
  });

  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "instructions.txt", mimeType: "text/plain", buffer: Buffer.from("Provide a transcript.")
  });
  await page.getByRole("button", { name: "Extract and save requirements" }).click();
  await expect(page.getByRole("heading", { name: "Saved requirements (1)" })).toBeVisible();
  await expect(page.getByText("Source: instructions.txt")).toBeVisible();
  await expect(page.locator("blockquote")).toHaveText("Provide a transcript.");
  await expect(page.getByText("Satisfaction evidence: 0 item(s).")).toBeVisible();
  await expect(page.getByText(/Instruction excerpts are source provenance/)).toBeVisible();
});

test("provenance lookup failure remains visible without losing saved requirements", async ({ page }) => {
  await page.route("**/v1/documents", async (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ id: DOCUMENT_ID })
  }));
  await page.route(`**/v1/documents/${DOCUMENT_ID}/requirements/persist`, async (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ workspace_id: WORKSPACE_ID, requirements: [] })
  }));
  await page.route(`**/v1/documents/${DOCUMENT_ID}/requirement-sources`, async (route) => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Unavailable" })
  }));
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "instructions.txt", mimeType: "text/plain", buffer: Buffer.from("Hello")
  });
  await page.getByRole("button", { name: "Extract and save requirements" }).click();
  await expect(page.getByRole("heading", { name: "Saved requirements (0)" })).toBeVisible();
  await expect(page.getByRole("alert", { name: /Source excerpts could not be loaded/ })).toBeVisible();
});
