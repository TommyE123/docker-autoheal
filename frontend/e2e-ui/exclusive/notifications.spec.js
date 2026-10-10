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

test(
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

// ntfy access-token authentication (#442). The token is optional, masked while typing,
// and stored with the service; the request header it produces is covered by the unit
// tests, because the e2e suite has no endpoint the app under test can reach.
const tokenField = (dialog) => dialog.getByPlaceholder("tk_...");

const storedService = async (request, name) => {
  const config = await (await request.get("/api/notifications/config")).json();
  return config.services.find((service) => service.name === name);
};

test(
  "adds an ntfy service with an access token, masked in the form and stored with it",
  { tag: ["@notifications", "@regression"] },
  async ({ page, request }) => {
    await page.goto("/notifications");
    await addServiceButton(page).click();

    const dialog = dialogTitled(page, "Add Notification Service");
    const save = dialog.getByRole("button", { name: "Add Service" });
    await dialog.getByPlaceholder("My Discord Server").fill("E2E Ntfy Token");
    await dialog.getByRole("combobox").selectOption("ntfy");

    // The token is optional: the topic alone is enough to save.
    await dialog.getByPlaceholder("docker-autoheal").fill("e2e-alerts");
    await expect(save).toBeEnabled();

    const token = tokenField(dialog);
    await expect(token).toHaveAttribute("type", "password");
    await token.fill("tk_e2e_secret");
    await save.click();

    await expect(
      alertWith(page, "Notification service added successfully"),
    ).toBeVisible();
    await expect(
      page.getByRole("row", { name: /E2E Ntfy Token/ }),
    ).toContainText("Ntfy");
    // The token is not shown anywhere on the page.
    await expect(page.getByText("tk_e2e_secret")).toHaveCount(0);

    const service = await storedService(request, "E2E Ntfy Token");
    expect(service).toMatchObject({
      type: "ntfy",
      topic: "e2e-alerts",
      access_token: "tk_e2e_secret",
    });
  },
);

test(
  "an ntfy service without a token is stored without one",
  { tag: "@notifications" },
  async ({ page, request }) => {
    await page.goto("/notifications");
    await addServiceButton(page).click();

    const dialog = dialogTitled(page, "Add Notification Service");
    await dialog.getByPlaceholder("My Discord Server").fill("E2E Ntfy Open");
    await dialog.getByRole("combobox").selectOption("ntfy");
    await dialog.getByPlaceholder("docker-autoheal").fill("e2e-open");
    await dialog.getByRole("button", { name: "Add Service" }).click();

    await expect(
      alertWith(page, "Notification service added successfully"),
    ).toBeVisible();
    const service = await storedService(request, "E2E Ntfy Open");
    expect(service.access_token ?? null).toBeNull();
  },
);

test(
  "editing an ntfy service keeps its token, and clearing the field removes it",
  { tag: ["@notifications", "@regression"] },
  async ({ page, request }) => {
    const created = await request.post("/api/notifications/services", {
      data: {
        name: "E2E Ntfy Edit",
        type: "ntfy",
        enabled: true,
        topic: "e2e-edit",
        access_token: "tk_e2e_edit",
      },
    });
    expect(created.ok()).toBeTruthy();
    await page.goto("/notifications");

    const row = page.getByRole("row", { name: /E2E Ntfy Edit/ });
    await row.getByRole("button", { name: "Edit" }).click();
    const dialog = dialogTitled(page, "Edit Notification Service");
    await expect(tokenField(dialog)).toHaveValue("tk_e2e_edit");

    // Saving without touching the token leaves it in place.
    await dialog.getByPlaceholder("docker-autoheal").fill("e2e-edit-2");
    await dialog.getByRole("button", { name: "Update Service" }).click();
    await expect(
      alertWith(page, "Notification service updated successfully"),
    ).toBeVisible();
    expect(await storedService(request, "E2E Ntfy Edit")).toMatchObject({
      topic: "e2e-edit-2",
      access_token: "tk_e2e_edit",
    });

    // Emptying the field removes the token.
    await row.getByRole("button", { name: "Edit" }).click();
    await tokenField(dialog).fill("");
    await dialog.getByRole("button", { name: "Update Service" }).click();
    await expect(
      alertWith(page, "Notification service updated successfully").last(),
    ).toBeVisible();
    const service = await storedService(request, "E2E Ntfy Edit");
    expect(service.access_token ?? null).toBeNull();
  },
);

test(
  "a failing ntfy delivery does not reveal the token",
  { tag: ["@notifications", "@errors"] },
  async ({ page, request }) => {
    // Nothing listens on port 9 inside the app container, so the delivery fails.
    const created = await request.post("/api/notifications/services", {
      data: {
        name: "E2E Ntfy Unreachable",
        type: "ntfy",
        enabled: true,
        topic: "e2e-unreachable",
        server_url: "http://127.0.0.1:9",
        access_token: "tk_e2e_leak_check",
      },
    });
    expect(created.ok()).toBeTruthy();

    const response = await request.post(
      "/api/notifications/test/E2E Ntfy Unreachable",
    );
    expect(await response.text()).not.toContain("tk_e2e_leak_check");

    await page.goto("/notifications");
    const row = page.getByRole("row", { name: /E2E Ntfy Unreachable/ });
    await row.getByRole("button", { name: "Test" }).click();
    await expect(page.getByRole("alert").first()).toBeVisible();
    await expect(page.getByText("tk_e2e_leak_check")).toHaveCount(0);
  },
);
