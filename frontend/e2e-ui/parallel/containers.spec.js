import { test, expect, dialogTitled } from "../fixtures.js";
import { inspectContainer, RUN_LABEL, stopContainer } from "../docker.js";

const rowFor = (page, name) => page.getByRole("row", { name });

// What the Containers page should show for each shared container. Only the first is
// part of @smoke: the rest are the same list rendering with different data.
const sharedStates = [
  {
    key: "monitored",
    title: "a running container with the monitor label is shown as monitored",
    status: "running",
    health: "N/A",
    monitored: true,
    tag: ["@smoke", "@containers", "@monitoring"],
  },
  {
    key: "unmonitored",
    title: "a running container without the label is not monitored",
    status: "running",
    health: "N/A",
    monitored: false,
    tag: ["@containers", "@monitoring"],
  },
  {
    key: "unhealthy",
    title: "a failing health check is shown as unhealthy",
    status: "running",
    health: "unhealthy",
    monitored: false,
    tag: ["@containers", "@monitoring"],
  },
  {
    key: "exited",
    title: "a stopped container is listed as exited",
    status: "exited",
    health: "N/A",
    monitored: false,
    tag: ["@containers"],
  },
];

for (const state of sharedStates) {
  test(state.title, { tag: state.tag }, async ({ page, sharedContainers }) => {
    const name = sharedContainers[state.key];
    await page.goto("/containers");

    const row = rowFor(page, name);
    await expect(row).toBeVisible();
    await expect(row.getByRole("cell", { name: "alpine:3.22" })).toBeVisible();
    await expect(
      row.getByRole("cell", { name: state.status, exact: true }),
    ).toBeVisible();
    await expect(
      row.getByRole("cell", { name: state.health, exact: true }),
    ).toBeVisible();
    await expect(row.getByText("Yes", { exact: true })).toHaveCount(
      state.monitored ? 1 : 0,
    );
  });
}

test(
  "the dashboard reflects the Docker daemon",
  { tag: ["@smoke", "@containers"] },
  async ({ page, sharedContainers }) => {
    expect(sharedContainers.monitored).toBeTruthy();
    await page.goto("/containers");

    const navigation = page.getByRole("navigation");
    await expect(navigation.getByText("Active")).toBeVisible();
    // "<monitored>/<total> monitored"; the total covers at least the shared containers.
    const summary = navigation.getByText(/\d+\/\d+ monitored/);
    await expect(summary).toBeVisible();
    const total = Number((await summary.innerText()).match(/\/(\d+)/)[1]);
    expect(total).toBeGreaterThanOrEqual(3);
  },
);

test(
  "a container's details open in a dialog",
  { tag: "@containers" },
  async ({ page, sharedContainers }) => {
    const name = sharedContainers.monitored;
    await page.goto("/containers");
    await rowFor(page, name).getByText(name, { exact: true }).click();

    const dialog = dialogTitled(page, "Container Details");
    await expect(dialog.getByRole("cell", { name, exact: true })).toBeVisible();
    await expect(dialog.getByText(RUN_LABEL)).toBeVisible();

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
  },
);

test(
  "restarting a container from the UI restarts it in Docker",
  { tag: ["@smoke", "@containers"] },
  async ({ page, createContainer }) => {
    const name = await createContainer({ suffix: "restart" });
    const startedBefore = await inspectContainer(name, "{{.State.StartedAt}}");
    await page.goto("/containers");

    await rowFor(page, name).getByRole("button", { name: "Restart" }).click();
    const dialog = dialogTitled(page, "Restart Container");
    await expect(
      dialog.getByText(`Are you sure you want to restart container "${name}"?`),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Confirm" }).click();

    await expect(page.getByRole("alert")).toContainText(
      `Container "${name}" restarted`,
    );
    await expect
      .poll(() => inspectContainer(name, "{{.State.StartedAt}}"))
      .not.toBe(startedBefore);
  },
);

test(
  "the list follows a container that stops",
  { tag: ["@containers", "@monitoring"] },
  async ({ page, createContainer }) => {
    const name = await createContainer({ suffix: "stop" });
    await page.goto("/containers");
    const row = rowFor(page, name);
    await expect(
      row.getByRole("cell", { name: "running", exact: true }),
    ).toBeVisible();

    await stopContainer(name);

    // The page refreshes itself every 5 seconds; no reload.
    await expect(
      row.getByRole("cell", { name: "exited", exact: true }),
    ).toBeVisible({
      timeout: 15000,
    });
  },
);

test(
  "auto-heal can be enabled and disabled for a container",
  { tag: ["@containers", "@monitoring"] },
  async ({ page, createContainer }) => {
    const name = await createContainer({ suffix: "select" });
    await page.goto("/containers");
    const row = rowFor(page, name);
    await expect(row).toBeVisible();
    await expect(row.getByText("Yes", { exact: true })).toHaveCount(0);

    await row.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Enable Auto-Heal" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "Enabled auto-heal for 1 container(s)",
    );
    await expect(row.getByText("Yes", { exact: true })).toBeVisible();

    await row.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Disable Auto-Heal" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "Disabled auto-heal for 1 container(s)",
    );
    await expect(row.getByText("Yes", { exact: true })).toHaveCount(0);
  },
);

test(
  "shows an error when the containers cannot be loaded",
  { tag: ["@smoke", "@errors", "@containers"] },
  async ({ page }) => {
    await page.route(/\/api\/containers(\?|$)/, (route) =>
      route.fulfill({ status: 500, json: { detail: "Docker unavailable" } }),
    );
    await page.goto("/containers");

    await expect(page.getByRole("alert")).toContainText(
      "Failed to load containers",
    );
    await expect(page.getByText("No containers found")).toBeVisible();
  },
);

test(
  "shows a loading state until the containers arrive",
  { tag: ["@errors", "@containers"] },
  async ({ page }) => {
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    await page.route(/\/api\/containers(\?|$)/, async (route) => {
      await gate;
      await route.continue();
    });
    await page.goto("/containers");

    await expect(page.getByText("Loading containers...")).toBeVisible();
    release();
    await expect(page.getByText("Loading containers...")).toBeHidden();
    await expect(
      page.getByRole("heading", { name: /Containers$/ }),
    ).toBeVisible();
  },
);

test(
  "shows an error when a restart fails",
  { tag: ["@errors", "@containers"] },
  async ({ page, sharedContainers }) => {
    // Intercepted before it reaches Docker, so the shared container is untouched.
    await page.route(/\/api\/containers\/[^/]+\/restart$/, (route) =>
      route.fulfill({ status: 500, json: { detail: "restart failed" } }),
    );
    await page.goto("/containers");

    await rowFor(page, sharedContainers.unmonitored)
      .getByRole("button", { name: "Restart" })
      .click();
    await dialogTitled(page, "Restart Container")
      .getByRole("button", { name: "Confirm" })
      .click();

    await expect(page.getByRole("alert")).toContainText(
      "Failed to restart container",
    );
  },
);
