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

// The notifications page logs a failed test send; in the demo that failure is
// how the "nothing was sent" message reaches the page, so it is expected there.
const allowTestSendLog = () => {
  problems = problems.filter(
    (problem) => !problem.startsWith("console: Failed to test service:"),
  );
};

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

test("a notification test says nothing was sent", async ({ page }) => {
  const nothingSent = page.getByText(/^Demo: nothing was sent/);
  await page.goto("./notifications");

  await page.getByRole("button", { name: "Test Team chat" }).click();
  await expect(nothingSent).toBeVisible();

  await page.getByRole("button", { name: /Add Service$/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/Service Name/).fill("ops");
  await dialog.getByLabel(/Webhook URL/).fill("https://example.com/hook");
  await dialog.getByRole("button", { name: "Test", exact: true }).click();
  await expect(dialog.getByText(/^Demo: nothing was sent/)).toBeVisible();

  await expect(page.getByText(/Test notification sent/)).toHaveCount(0);
  allowTestSendLog();
});

test("Reset demo brings back the sample data", async ({ page }) => {
  const sampleEvent = page.getByText(
    "Container quarantined: exceeded 3 restarts in 600s window",
  );
  await page.goto("./events");
  await expect(sampleEvent).toBeVisible();

  await page.getByRole("button", { name: /Clear All$/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Clear All Events$/ })
    .click();
  await expect(sampleEvent).toHaveCount(0);

  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(sampleEvent).toBeVisible();
});
