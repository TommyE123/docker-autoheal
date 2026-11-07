import { test, expect } from "@playwright/test";

// The built demo: the real UI against the in-browser mock API. Unit tests cover
// the simulation and the mock; this checks they work together in a real build
// under the Pages sub-path. A UI call the mock doesn't answer shows up here as
// a console error.

// The optional Cloudflare Web Analytics beacon: its script host and the host
// it reports to. Stubbed below so the test never depends on Cloudflare.
const ANALYTICS = /^https:\/\/(static\.)?cloudflareinsights\.com\//;

// Nav link names start with an icon-font glyph, so match the end of the name.
const navLink = (page, name) =>
  page.getByRole("link", { name: new RegExp(`${name}$`) });

let problems;

test.beforeEach(async ({ page }) => {
  problems = [];
  await page.route(ANALYTICS, (route) =>
    route.fulfill({ status: 204, body: "" }),
  );
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page error: ${error}`));
  page.on("requestfailed", (request) =>
    problems.push(`failed request: ${request.url()}`),
  );
  page.on("request", (request) => {
    const { host } = new URL(request.url());
    if (host !== "localhost:4174" && !ANALYTICS.test(request.url())) {
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

  // Headings, like nav links, can start with an icon glyph.
  for (const [link, path, heading] of [
    ["Events", "events", "Event Log"],
    ["Notifications", "notifications", "Notification Services"],
    ["Configuration", "config", "Monitor Settings"],
    ["Containers", "containers", "Dashboard"],
  ]) {
    await navLink(page, link).click();
    await expect(page).toHaveURL(new RegExp(`/docker-autoheal/${path}$`));
    await expect(
      page.getByRole("heading", { name: new RegExp(`${heading}$`) }),
    ).toBeVisible();
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
  await expect(page.getByRole("heading", { name: /Event Log$/ })).toBeVisible();
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
