import { expect, test } from "@playwright/test";

const ACTION_ID = "11111111-1111-4111-8111-111111111111";

test("workflow inspector validates IDs without calling the API", async ({ page }) => {
  let calls = 0;
  await page.route("**/v1/workflows/**", async (route) => {
    calls += 1;
    await route.fulfill({ status: 500, body: "Unexpected request" });
  });
  await page.goto("/");
  await page.getByLabel("Action UUID").fill("not-a-uuid");
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByRole("alert")).toContainText("Enter a valid action UUID.");
  expect(calls).toBe(0);
});

test("workflow inspector displays persisted checkpoint and clears stale results", async ({ page }) => {
  await page.route("**/v1/workflows/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        action_id: ACTION_ID,
        status: "awaiting_approval",
        attempt: 1,
        max_attempts: 3,
        idempotency_key: "review:demo",
        last_error: null,
      }),
    });
  });
  await page.goto("/");
  await page.getByLabel("Action UUID").fill(ACTION_ID);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("awaiting approval")).toBeVisible();
  await expect(page.getByText("1 / 3")).toBeVisible();
  await expect(page.getByText("review:demo")).toBeVisible();

  await page.getByLabel("Action UUID").fill("bad");
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByRole("alert")).toContainText("Enter a valid action UUID.");
  await expect(page.getByText("awaiting approval")).toHaveCount(0);
});

test("workflow inspector handles missing checkpoints without stale data", async ({ page }) => {
  await page.route("**/v1/workflows/**", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Workflow not found" }),
    });
  });
  await page.goto("/");
  await page.getByLabel("Action UUID").fill(ACTION_ID);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByRole("alert")).toContainText("Workflow not found");
  await expect(page.getByText("Attempts:")).toHaveCount(0);
});
