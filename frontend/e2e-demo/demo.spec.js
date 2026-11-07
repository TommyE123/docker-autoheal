import { test, expect } from "@playwright/test";

// The built demo: the real UI against the in-browser mock API. Unit tests cover
// the simulation and the mock; this checks they work together in a real build
// under the Pages sub-path. A UI call the mock doesn't answer shows up here as
// a console error.

// Hosts the demo may contact besides itself: the optional analytics beacon.
const ALLOWED_HOSTS = new Set(["static.cloudflareinsights.com"]);

// Nav link names start with an icon-font glyph, so match the end of the name.
const navLink = (page, name) =>
  page.getByRole("link", { name: new RegExp(`${name}$`) });

let problems;

test.beforeEach(async ({ page }) => {
  problems = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page error: ${error}`));
  page.on("requestfailed", (request) =>
    problems.push(`failed request: ${request.url()}`),
  );
  page.on("request", (request) => {
    const { host } = new URL(request.url());
    if (host !== "localhost:4174" && !ALLOWED_HOSTS.has(host)) {
      problems.push(`off-site request: ${request.url()}`);
    }
  });
});

test.afterEach(() => {
  expect(problems).toEqual([]);
});

test("every page works against the mock, with the banner and no service worker", async ({
  page,
}) => {
  await page.goto("./");
  await expect(page).toHaveURL(/\/docker-autoheal\/containers$/);
  await expect(
    page.getByText("Simulated demo: no real containers."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Restart shop-web-1" }),
  ).toBeVisible();

  for (const [link, heading] of [
    ["Events", "Event Log"],
    ["Notifications", "Notification"],
    ["Configuration", "Monitor Settings"],
    ["Containers", "Dashboard"],
  ]) {
    await navLink(page, link).click();
    await expect(page.getByText(heading).first()).toBeVisible();
  }

  expect(
    await page.evaluate(async () =>
      navigator.serviceWorker
        ? (await navigator.serviceWorker.getRegistrations()).length
        : 0,
    ),
  ).toBe(0);
  await expect(page.locator('link[rel="manifest"]')).toHaveCount(0);
});

test("a deep link loads the app", async ({ page }) => {
  await page.goto("./events");
  await expect(page.getByText("Event Log")).toBeVisible();
  await expect(
    page.getByText("Simulated demo: no real containers."),
  ).toBeVisible();
});

test("Autoheal restarts a crashed container", async ({ page }) => {
  await page.goto("./containers");
  const controls = page.locator("#demo-controls tr", { hasText: "shop-db-1" });
  await controls.getByRole("button", { name: "Crash", exact: true }).click();
  await expect(controls.getByText("stopped")).toBeVisible();

  // Next 5s check schedules a 5s backoff wait, then the restart.
  await expect(controls.getByText("running")).toBeVisible({ timeout: 20000 });
  await navLink(page, "Events").click();
  await expect(
    page.getByText("Restart successful: Container exited with code 1").first(),
  ).toBeVisible();
  await expect(
    page.getByText("shop-db-1 (compose:shop:db#1)").first(),
  ).toBeVisible();
});
