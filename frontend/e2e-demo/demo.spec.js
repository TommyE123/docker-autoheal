import { test, expect } from "@playwright/test";

// The built demo: the real UI against the in-browser mock API, under the Pages
// sub-path. A UI call the mock doesn't answer shows up here as a console error.

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
    page.getByText("Demo with sample data: no real containers."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Restart web" })).toBeVisible();

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
    page.getByText("Demo with sample data: no real containers."),
  ).toBeVisible();
});
