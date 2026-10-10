import { exclusiveTest as test, expect, dialogTitled } from "../fixtures.js";

const emptyStateText = /No notification services configured/;

// Every test starts from "no services, notifications off". The configuration is
// restored afterwards by the exclusive fixture.
test.beforeEach(async ({ request }) => {
  const response = await request.put("/api/notifications/config", {
    data: { enabled: false, services: [] },
  });
  expect(response.ok()).toBeTruthy();
});

// The empty state is itself an alert, so pick feedback alerts by their text.
const alertWith = (page, text) =>
  page.getByRole("alert").filter({ hasText: text });

const addServiceButton = (page) =>
  page.getByRole("button", { name: "+ Add Service" });

test(
  "explains that no notification services are configured",
  { tag: "@notifications" },
  async ({ page }) => {
    await page.goto("/notifications");

    await expect(
      page.getByRole("heading", { name: "Notifications", exact: true }),
    ).toBeVisible();
    await expect(page.getByText(emptyStateText)).toBeVisible();
    await expect(page.getByText("Notifications are disabled")).toBeVisible();
  },
);

test(
  "adds a webhook service, lists it, then deletes it",
  { tag: "@notifications" },
  async ({ page }) => {
    await page.goto("/notifications");
    await addServiceButton(page).click();

    const dialog = dialogTitled(page, "Add Notification Service");
    const save = dialog.getByRole("button", { name: "Add Service" });
    await expect(save).toBeDisabled();
    await dialog.getByPlaceholder("My Discord Server").fill("E2E Webhook");
    await dialog
      .getByPlaceholder("https://example.com/webhook")
      .fill("https://example.com/hook");
    await expect(save).toBeEnabled();
    await save.click();

    await expect(
      alertWith(page, "Notification service added successfully"),
    ).toBeVisible();
    await expect(dialog).toBeHidden();
    const row = page.getByRole("row", { name: /E2E Webhook/ });
    await expect(row).toContainText("Generic Webhook");
    await expect(row).toContainText("Enabled");
    await expect(page.getByText(emptyStateText)).toBeHidden();

    page.once("dialog", (confirm) => confirm.accept());
    await row.getByRole("button", { name: "Delete" }).click();
    await expect(
      alertWith(page, "Notification service deleted successfully"),
    ).toBeVisible();
    await expect(page.getByText(emptyStateText)).toBeVisible();
  },
);

test(
  "only offers Add Service once the selected type's required fields are filled",
  { tag: ["@notifications", "@regression"] },
  async ({ page }) => {
    await page.goto("/notifications");
    await addServiceButton(page).click();

    const dialog = dialogTitled(page, "Add Notification Service");
    const save = dialog.getByRole("button", { name: "Add Service" });
    await dialog.getByPlaceholder("My Discord Server").fill("E2E Telegram");
    await dialog.getByRole("combobox").selectOption("telegram");
    await expect(save).toBeDisabled();

    await dialog
      .getByPlaceholder("123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
      .fill("123456:token");
    await expect(save).toBeDisabled();
    await dialog.getByPlaceholder("-1001234567890").fill("-100123");
    await expect(save).toBeEnabled();
  },
);

test(
  "shows the server's reason when a service name is already taken",
  { tag: ["@notifications", "@errors"] },
  async ({ page, request }) => {
    const existing = await request.post("/api/notifications/services", {
      data: {
        name: "E2E Duplicate",
        type: "webhook",
        enabled: true,
        url: "https://example.com/hook",
      },
    });
    expect(existing.ok()).toBeTruthy();
    await page.goto("/notifications");
    await addServiceButton(page).click();

    const dialog = dialogTitled(page, "Add Notification Service");
    await dialog.getByPlaceholder("My Discord Server").fill("E2E Duplicate");
    await dialog
      .getByPlaceholder("https://example.com/webhook")
      .fill("https://example.com/other");
    await dialog.getByRole("button", { name: "Add Service" }).click();

    await expect(
      alertWith(page, "Service with name 'E2E Duplicate' already exists"),
    ).toBeVisible();
    await expect(dialog).toBeVisible();
  },
);

test(
  "turns notifications on",
  { tag: "@notifications" },
  async ({ page, request }) => {
    await page.goto("/notifications");

    // The master switch is the page's only checkbox (its label is not linked to it).
    await page.getByRole("checkbox").click();
    await expect(alertWith(page, "Notifications enabled")).toBeVisible();
    await expect(page.getByText("Notifications are enabled")).toBeVisible();
    const config = await (
      await request.get("/api/notifications/config")
    ).json();
    expect(config.enabled).toBe(true);
  },
);

// Blocked by https://github.com/TommyE123/docker-autoheal/issues/455: `.alert` is
// position: fixed with z-index 9999 for every alert, so the empty-state alert paints
// over the modal. Enable this test, unchanged, when that fix merges.
test.fixme(
  "the empty-state alert stays behind the Add Service modal (#455)",
  { tag: ["@notifications", "@regression"] },
  async ({ page }) => {
    await page.goto("/notifications");
    const emptyState = page.getByText(emptyStateText);
    await expect(emptyState).toBeVisible();

    await addServiceButton(page).click();
    const dialog = dialogTitled(page, "Add Notification Service");
    await expect(dialog).toBeVisible();

    // Hit-test the centre of the alert: with the modal open, whatever is painted
    // there must not be the alert itself.
    const alertIsOnTop = await emptyState.evaluate((alert) => {
      const box = alert.getBoundingClientRect();
      const topmost = document.elementFromPoint(
        box.x + box.width / 2,
        box.y + box.height / 2,
      );
      return alert.contains(topmost);
    });
    expect(alertIsOnTop).toBe(false);

    // A real click fails if anything else is painted over the field.
    const name = dialog.getByPlaceholder("My Discord Server");
    await name.click();
    await name.fill("E2E Overlap");
    await expect(name).toHaveValue("E2E Overlap");
  },
);
