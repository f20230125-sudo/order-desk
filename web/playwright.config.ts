import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real app in a real browser.
// Locally: Flask on 5181 with a freshly seeded database, Vite on 5180 (it passes /api to Flask).
//   python -m backend.db.seed --reset   then   npx playwright test
// Against the published site: BASE_URL=https://order-desk-ops.vercel.app npx playwright test
// Tests that change data (settling a problem, adding a document) run only locally, or with E2E_WRITES=1,
// so a test run never uses up the demo's sample documents before visitors try them.
const remote = process.env.BASE_URL;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: { baseURL: remote ?? "http://127.0.0.1:5180", trace: "retain-on-failure", reducedMotion: "reduce" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
