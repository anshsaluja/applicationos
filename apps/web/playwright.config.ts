import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // Never let test.only silently reduce coverage in CI.
  forbidOnly: Boolean(process.env.CI),
  // Bound hung browser actions while retaining diagnostics for failures.
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: process.env.APPLICATIONOS_REAL_E2E === "1" || !process.env.CI,
    timeout: 120_000,
  },
});
