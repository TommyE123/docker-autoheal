import { test as base, expect } from "@playwright/test";
import { inspectContainer, removeNamed, startContainer } from "./docker.js";

export { expect };

// The app's modals have role="dialog" but no accessible name, so find one by its title.
export const dialogTitled = (page, title) =>
  page
    .getByRole("dialog")
    .filter({ has: page.getByText(title, { exact: true }) });

const runId = () => process.env.UI_E2E_RUN_ID;
const containerName = (suffix) => `e2e-ui-${runId()}-${suffix}`;

/**
 * The label the app under test monitors. Reading it from the app, and refusing
 * anything but the development label, is the second half of the safety guard: the
 * suite only creates monitored containers on a dev stack, never on an instance
 * watching the production `autoheal=true` label.
 */
async function readMonitorLabel(playwright, baseURL) {
  const context = await playwright.request.newContext({ baseURL });
  try {
    const response = await context.get("/api/config");
    expect(response.ok(), `GET ${baseURL}/api/config`).toBeTruthy();
    const { monitor } = await response.json();
    if (
      monitor.label_key !== "autoheal.dev" ||
      monitor.label_value !== "true"
    ) {
      throw new Error(
        `${baseURL} monitors ${monitor.label_key}=${monitor.label_value}, not the ` +
          "development label autoheal.dev=true. Refusing to create containers for it.",
      );
    }
    return { [monitor.label_key]: monitor.label_value };
  } finally {
    await context.dispose();
  }
}

export const test = base.extend({
  monitorLabel: [
    async ({ playwright }, provide, workerInfo) => {
      await provide(
        await readMonitorLabel(playwright, workerInfo.project.use.baseURL),
      );
    },
    { scope: "worker" },
  ],

  /**
   * One small set of containers for tests that only read, one per run, created on
   * first use and shared by every worker (a worker that loses the name race reuses
   * the winner's container). They cover the states the Containers page shows.
   */
  sharedContainers: [
    async ({ monitorLabel }, provide) => {
      const sleep = ["sleep", "3600"];
      const containers = {
        monitored: {
          name: containerName("monitored"),
          labels: monitorLabel,
          command: sleep,
        },
        unmonitored: { name: containerName("unmonitored"), command: sleep },
        exited: { name: containerName("exited"), command: ["true"] },
        unhealthy: {
          name: containerName("unhealthy"),
          options: [
            "--health-cmd",
            "exit 1",
            "--health-interval",
            "1s",
            "--health-retries",
            "1",
          ],
          command: sleep,
        },
      };
      await Promise.all(
        Object.values(containers).map((container) =>
          startContainer({ runId: runId(), ...container }),
        ),
      );
      // A worker that lost the creation race may get here before the winner has
      // finished, so wait for every container to reach the state its tests expect.
      const expectedState = {
        monitored: ["{{.State.Status}}", "running"],
        unmonitored: ["{{.State.Status}}", "running"],
        exited: ["{{.State.Status}}", "exited"],
        unhealthy: ["{{.State.Health.Status}}", "unhealthy"],
      };
      for (const [key, [format, value]] of Object.entries(expectedState)) {
        await expect
          .poll(() => inspectContainer(containers[key].name, format), {
            timeout: 60000,
          })
          .toBe(value);
      }
      await provide(
        Object.fromEntries(
          Object.entries(containers).map(([key, { name }]) => [key, name]),
        ),
      );
    },
    // Includes pulling the image on a cold daemon.
    { scope: "worker", timeout: 180000 },
  ],

  /**
   * A container owned by a single test, for tests that change a container's state
   * (restart, stop, enable monitoring). Unmonitored by default so Autoheal never acts
   * on it; `monitored: true` adds the dev monitor label. Removed after the test.
   */
  createContainer: async ({ monitorLabel }, provide) => {
    const created = [];
    await provide(
      async ({ suffix, monitored = false, command = ["sleep", "3600"] }) => {
        const name = containerName(
          `${suffix}-${Math.random().toString(16).slice(2, 6)}`,
        );
        await startContainer({
          name,
          runId: runId(),
          labels: monitored ? monitorLabel : {},
          command,
        });
        created.push(name);
        return name;
      },
    );
    if (created.length > 0) {
      await removeNamed(created);
    }
  },
});

/**
 * For tests in the `exclusive` project, which change state shared by the whole app.
 * The app's configuration (which includes the notification services) is restored after
 * every test. The event log cannot be restored through the API; it only ever holds
 * the development stack's own events.
 */
export const exclusiveTest = test.extend({
  appStateRestored: [
    async ({ request }, provide) => {
      const response = await request.get("/api/config");
      expect(response.ok()).toBeTruthy();
      const snapshot = await response.json();
      await provide();
      const restore = await request.put("/api/config", { data: snapshot });
      expect(restore.ok(), "restoring the app configuration").toBeTruthy();
    },
    { auto: true },
  ],
});
