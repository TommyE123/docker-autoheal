import { exclusiveTest as test, expect, dialogTitled } from "../fixtures.js";

// Starting a container that carries the dev monitor label makes Autoheal log an
// "auto_monitor" event for it straight away, which gives these tests a real event
// without waiting for a monitoring cycle.
async function startMonitoredContainer(createContainer, request, suffix) {
  const name = await createContainer({ suffix, monitored: true });
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/events", {
          params: { container: name },
        });
        return (await response.json()).length;
      },
      { timeout: 30000 },
    )
    .toBeGreaterThan(0);
  return name;
}

test.beforeEach(async ({ request }) => {
  const response = await request.delete("/api/events");
  expect(response.ok()).toBeTruthy();
});

test(
  "shows an empty state when nothing has been logged",
  { tag: "@events" },
  async ({ page }) => {
    await page.goto("/events");

    await expect(page.getByText("No events recorded yet")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Clear All" }),
    ).toBeDisabled();
  },
);

test(
  "lists the details of an event Autoheal logged",
  { tag: ["@events", "@monitoring"] },
  async ({ page, request, createContainer }) => {
    const name = await startMonitoredContainer(createContainer, request, "ev");
    await page.goto("/events");

    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByText("auto_monitor", { exact: true })).toBeVisible();
    await expect(page.getByText("enabled", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Automatically added to monitoring"),
    ).toBeVisible();
    await expect(page.getByText("Container ID:")).toBeVisible();
  },
);

test(
  "Autoheal restarts a container that exits and logs the restart",
  { tag: ["@events", "@monitoring", "@regression"] },
  async ({ page, request, createContainer }) => {
    test.setTimeout(120000);
    // A short monitoring interval makes the restart observable quickly.
    const config = await (await request.get("/api/config")).json();
    const updated = await request.put("/api/config/monitor", {
      data: { ...config.monitor, interval_seconds: 2 },
    });
    expect(updated.ok()).toBeTruthy();

    const name = await createContainer({
      suffix: "victim",
      monitored: true,
      command: ["sh", "-c", "sleep 3; exit 1"],
    });
    await expect
      .poll(
        async () => {
          const response = await request.get("/api/events", {
            params: { event_type: "restart", container: name },
          });
          return (await response.json()).map((event) => event.status);
        },
        { timeout: 90000 },
      )
      .toContain("success");

    await page.goto("/events");
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(
      page.getByText("restart", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText("success", { exact: true }).first(),
    ).toBeVisible();
  },
);

test(
  "clearing the log asks for confirmation and then empties it",
  { tag: "@events" },
  async ({ page, request, createContainer }) => {
    const name = await startMonitoredContainer(
      createContainer,
      request,
      "clear",
    );
    await page.goto("/events");
    await expect(page.getByRole("heading", { name })).toBeVisible();

    await page.getByRole("button", { name: "Clear All" }).click();
    const dialog = dialogTitled(page, "Confirm Clear Events");
    await expect(dialog).toContainText(
      /\d+ events? will be permanently deleted/,
    );

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("heading", { name })).toBeVisible();

    await page.getByRole("button", { name: "Clear All" }).click();
    await dialog.getByRole("button", { name: "Clear All Events" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "All events cleared successfully!",
    );
    await expect(page.getByText("No events recorded yet")).toBeVisible();
  },
);

// Blocked by https://github.com/TommyE123/docker-autoheal/pull/431: the Events page
// has no filters on main yet. Enable this test, unchanged, when that PR merges.
test.fixme(
  "filters the log by container and event type, and clears the filters (#431)",
  { tag: ["@events", "@regression"] },
  async ({ page, request, createContainer }) => {
    const first = await startMonitoredContainer(createContainer, request, "fa");
    const second = await startMonitoredContainer(
      createContainer,
      request,
      "fb",
    );
    await page.goto("/events");
    await expect(page.getByRole("heading", { name: first })).toBeVisible();
    await expect(page.getByRole("heading", { name: second })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Clear Filters" }),
    ).toBeHidden();

    await page.getByLabel("Container", { exact: true }).selectOption(first);
    await expect(page.getByRole("heading", { name: first })).toBeVisible();
    await expect(page.getByRole("heading", { name: second })).toBeHidden();

    // Both containers only have auto_monitor events, so another type matches nothing.
    await page
      .getByLabel("Event Type")
      .selectOption({ label: "Container Restart" });
    await expect(page.getByText("No events recorded yet")).toBeVisible();

    await page.getByLabel("Event Type").selectOption({ label: "Auto Monitor" });
    await expect(page.getByRole("heading", { name: first })).toBeVisible();

    await page.getByRole("button", { name: "Clear Filters" }).click();
    await expect(page.getByRole("heading", { name: first })).toBeVisible();
    await expect(page.getByRole("heading", { name: second })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Clear Filters" }),
    ).toBeHidden();
  },
);
