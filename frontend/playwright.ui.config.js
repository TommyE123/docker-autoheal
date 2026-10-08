import { defineConfig, devices } from "@playwright/test";

// UI E2E: real user journeys against the development stack running on the Dev
// Container's isolated Docker daemon (docker-compose.dev.yml, PR #461). This is
// deliberately separate from playwright.config.js, which is the Production Image
// Smoke: that one proves the shipped image on port 3131 with a single worker, this
// one needs parallel workers, Docker fixtures and tag selection, and must never be
// pointed at a production instance. See docs/developer/testing.md.
//
// The base URL has its own variable (not E2E_BASE_URL, which the production smoke
// sets to port 3131) so a stray environment value cannot aim this suite at production.

// Selects tests by tag, e.g. UI_E2E_TAG=@events. This is set per project rather than
// passed as --grep because the CLI filter does not apply to a dependency project: with
// `--grep @events`, the exclusive project would still pull in every `parallel` test.
const tag = process.env.UI_E2E_TAG;
const grep = tag ? new RegExp(tag) : undefined;

export default defineConfig({
  testDir: "./e2e-ui",
  outputDir: "./test-results-ui",
  globalSetup: "./e2e-ui/globalSetup.js",
  globalTeardown: "./e2e-ui/globalTeardown.js",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [
        ["list"],
        ["html", { open: "never", outputFolder: "playwright-report-ui" }],
      ]
    : [["list"]],
  use: {
    baseURL: process.env.UI_E2E_BASE_URL || "http://localhost:3132",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      // Tests that only touch their own containers or only read shared state.
      name: "parallel",
      testMatch: "parallel/**/*.spec.js",
      grep,
      fullyParallel: true,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // Tests that change state shared by the whole app (/data: configuration,
      // notification services, the event log). One worker at a time, and only after
      // the parallel project, so nothing else is reading that state meanwhile.
      // `--no-deps` runs it alone.
      name: "exclusive",
      testMatch: "exclusive/**/*.spec.js",
      grep,
      workers: 1,
      dependencies: ["parallel"],
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
