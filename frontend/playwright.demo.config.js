import { defineConfig, devices } from "@playwright/test";

// Smoke test of the built browser demo (see docs/developer/demo.md). It serves
// an existing build, so run `npm run build:demo` first; `npm run test:demo-e2e`
// does not rebuild, so CI tests the exact files it deploys.
const port = 4174;

export default defineConfig({
  testDir: "./e2e-demo",
  outputDir: "./test-results-demo",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [
        ["list"],
        ["html", { open: "never", outputFolder: "playwright-report-demo" }],
      ]
    : [["list"]],
  use: {
    baseURL: `http://localhost:${port}/docker-autoheal/`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: `npx vite preview --mode demo --port ${port} --strictPort`,
    url: `http://localhost:${port}/docker-autoheal/`,
    reuseExistingServer: !process.env.CI,
  },
});
