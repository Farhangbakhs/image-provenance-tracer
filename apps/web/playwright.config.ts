import { defineConfig, devices } from "@playwright/test";

/** End-to-end tests run against demo mode (`make demo`): seeded cases, replayed providers, no keys. */
export default defineConfig({
  testDir: "./e2e",
  // Generous: the demo stack may share a small machine with its own build.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.ORIGIN_WEB_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    navigationTimeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
