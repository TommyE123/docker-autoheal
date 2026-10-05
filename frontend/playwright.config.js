import { defineConfig, devices } from '@playwright/test';

// E2E tests run against the Docker-served application (not the Vite dev
// server). See docs/developer/testing.md for how to start it locally.
export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3131',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
