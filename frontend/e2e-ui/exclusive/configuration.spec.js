import { exclusiveTest as test, expect, dialogTitled } from "../fixtures.js";

// The labels in the settings forms are not associated with their inputs (no
// controlId), so the fields are found by role inside the form that owns the
// "Save Monitor Settings" button. Switch to getByLabel once the labels are linked.
const monitorForm = (page) =>
  page.locator("form").filter({
    has: page.getByRole("button", { name: "Save Monitor Settings" }),
  });

async function currentMonitorConfig(request) {
  const response = await request.get("/api/config");
  expect(response.ok()).toBeTruthy();
  return (await response.json()).monitor;
}

test(
  "shows the current monitor configuration",
  { tag: "@configuration" },
  async ({ page, request }) => {
    const monitor = await currentMonitorConfig(request);
    await page.goto("/config");

    const form = monitorForm(page);
    await expect(form.getByRole("spinbutton")).toHaveValue(
      String(monitor.interval_seconds),
    );
    await expect(form.getByRole("textbox").first()).toHaveValue(
      monitor.label_key,
    );
    await expect(form.getByRole("textbox").nth(1)).toHaveValue(
      monitor.label_value,
    );
  },
);

test(
  "a saved monitoring interval is applied and survives a reload",
  { tag: "@configuration" },
  async ({ page, request }) => {
    const { interval_seconds: before } = await currentMonitorConfig(request);
    const interval = before === 45 ? 46 : 45;
    await page.goto("/config");

    const form = monitorForm(page);
    await form.getByRole("spinbutton").fill(String(interval));
    await form.getByRole("button", { name: "Save Monitor Settings" }).click();

    await expect(page.getByRole("alert")).toContainText(
      "Monitor configuration updated",
    );
    expect((await currentMonitorConfig(request)).interval_seconds).toBe(
      interval,
    );

    await page.reload();
    await expect(monitorForm(page).getByRole("spinbutton")).toHaveValue(
      String(interval),
    );
  },
);

test(
  "an interval that conflicts with the restart policy is rejected",
  { tag: ["@configuration", "@regression"] },
  async ({ page, request }) => {
    const before = await currentMonitorConfig(request);
    await page.goto("/config");

    const form = monitorForm(page);
    await form.getByRole("spinbutton").fill("100000");
    await form.getByRole("button", { name: "Save Monitor Settings" }).click();

    const dialog = dialogTitled(page, "Invalid Monitor Settings Configuration");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("monitoring cycles")).toBeVisible();

    await dialog
      .getByRole("button", { name: "Close and Adjust Settings" })
      .click();
    await expect(dialog).toBeHidden();
    expect(await currentMonitorConfig(request)).toEqual(before);
  },
);

test(
  "shows an error and keeps the old value when saving fails",
  { tag: ["@configuration", "@errors"] },
  async ({ page, request }) => {
    const before = await currentMonitorConfig(request);
    await page.route("**/api/config/monitor", (route) =>
      route.fulfill({ status: 500, json: { detail: "disk full" } }),
    );
    await page.goto("/config");

    const form = monitorForm(page);
    await form.getByRole("spinbutton").fill("45");
    await form.getByRole("button", { name: "Save Monitor Settings" }).click();

    await expect(page.getByRole("alert")).toContainText(
      "Failed to update monitor configuration",
    );
    expect(await currentMonitorConfig(request)).toEqual(before);
  },
);

test(
  "shows an error when the configuration cannot be loaded",
  { tag: ["@configuration", "@errors"] },
  async ({ page }) => {
    await page.route("**/api/config", (route) =>
      route.fulfill({ status: 500, json: { detail: "unavailable" } }),
    );
    await page.goto("/config");

    await expect(page.getByRole("alert")).toContainText(
      "Failed to load configuration",
    );
  },
);
