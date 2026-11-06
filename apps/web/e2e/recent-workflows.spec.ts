import { expect, test } from "@playwright/test";

const FIRST = "11111111-1111-4111-8111-111111111111";
const SECOND = "22222222-2222-4222-8222-222222222222";

function checkpoint(action_id: string) {
  return {
    action_id,
    status: "awaiting_approval",
    attempt: 0,
    max_attempts: 3,
    idempotency_key: `local:${action_id}`,
    last_error: null,
  };
}

test("recent checkpoints paginate and selecting a row opens persisted state", async ({ page }) => {
  const requested: string[] = [];
  await page.route("**/v1/workflows?*", async (route) => {
    const url = new URL(route.request().url());
    const offset = url.searchParams.get("offset");
    requested.push(offset ?? "");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(offset === "0"
        ? Array.from({ length: 10 }, (_, i) => checkpoint(i === 0 ? FIRST : `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`))
        : [checkpoint(SECOND)]),
    });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.getByRole("button", { name: "Refresh workflows" }).click();
  await expect(page.getByRole("list", { name: "Recent workflows" }).getByRole("listitem")).toHaveCount(10);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("list", { name: "Recent workflows" }).getByRole("listitem")).toHaveCount(1);
  await page.getByRole("list", { name: "Recent workflows" }).getByRole("button", { name: SECOND }).click();
  await expect(page.getByLabel("Action UUID")).toHaveValue(SECOND);
  await expect(page.getByText(`local:${SECOND}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page.getByRole("list", { name: "Recent workflows" }).getByRole("listitem")).toHaveCount(10);
  expect(requested).toEqual(["0", "10", "0"]);
});

test("failed refresh reports an error without erasing the last successful page", async ({ page }) => {
  let fail = false;
  await page.route("**/v1/workflows?*", async (route) => {
    if (fail) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Database unavailable" }) });
    } else {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([checkpoint(FIRST)]) });
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Refresh workflows" }).click();
  await expect(page.getByRole("list", { name: "Recent workflows" }).getByRole("button", { name: FIRST })).toBeVisible();
  fail = true;
  await page.getByRole("button", { name: "Refresh workflows" }).click();
  await expect(page.getByRole("alert")).toContainText("Database unavailable");
  await expect(page.getByRole("list", { name: "Recent workflows" }).getByRole("button", { name: FIRST })).toBeVisible();
});
