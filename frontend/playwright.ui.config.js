import { defineConfig, devices } from "@playwright/test";

// UI E2E: real user journeys, selected by tag, run by frontend/e2e-ui/run.sh. It needs an
// instance monitoring autoheal.dev=true on an isolated Docker daemon, which is either
//   - CI: a throwaway instance of the exact image docker-build.yml built, started by
//     production-smoke-test.yml, which sets UI_E2E_BASE_URL; or
//   - development: the dev stack of docker-compose.dev.yml in the Dev Container.
// It uses parallel workers and Docker fixtures, and must never be pointed at a production
// instance (the fixtures refuse one). See docs/developer/testing.md.
//
// The base URL has its own variable so a stray environment value (such as a generic
// E2E_BASE_URL) cannot aim this suite at production.

// Selects tests by tag, e.g. UI_E2E_TAG=@events. This is set per project rather than
// passed as --grep because the CLI filter does not apply to a dependency project: with
// `--grep @events`, the exclusive project would still pull in every `parallel` test.
const tag = process.env.UI_E2E_TAG;
const grep = tag ? new RegExp(tag) : undefined;

// Set by run.sh for UI mode only; see the `all` project below.
const uiMode = process.env.UI_E2E_UI_MODE === "1";

export default defineConfig({
  testDir: "./e2e-ui",
  outputDir: "./test-results-ui",
  globalSetup: "./e2e-ui/globalSetup.js",
  globalTeardown: "./e2e-ui/globalTeardown.js",
  // UI mode runs one project with every spec, so keep the tests from overlapping.
  workers: uiMode ? 1 : undefined,
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
  projects: uiMode
    ? [
        {
          // Playwright's UI mode ticks only the first project by default and offers no
          // way to preselect others, so with the two projects below, scopes whose tests
          // live in `exclusive` (notifications, events, configuration) showed "No
          // tests". run.sh therefore starts UI mode with this single project, which
          // holds every spec; `workers: 1` above keeps them from overlapping.
          name: "all",
          testMatch: "**/*.spec.js",
          grep,
          use: { ...devices["Desktop Chrome"] },
        },
      ]
    : [
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
