import { exclusiveTest as test, expect } from "../fixtures.js";
import {
  docker,
  inspectContainer,
  removeNamed,
  startContainer,
} from "../docker.js";

// The integration needs an Uptime-Kuma /metrics endpoint. A real server would make the
// suite depend on an external service, so a throwaway container serves a metrics file
// instead. The app calls it from inside its own container, so it joins the network
// the app runs on (the default bridge in CI, the Compose network in development).
// The file can be rewritten at runtime (setMonitorStatus) to flip a monitor's status.
// Requests without the expected Basic credentials get 401, as the real server answers.
const API_KEY = "e2e-key";
const RESTART_REASON = "Uptime-Kuma monitor reports DOWN";

async function appNetwork(baseURL) {
  const port = new URL(baseURL).port;
  const app = await docker([
    "ps",
    "--filter",
    `publish=${port}`,
    "--format",
    "{{.Names}}",
  ]);
  if (!app || app.includes("\n")) {
    throw new Error(
      `Expected one container publishing port ${port} (the app under test), found '${app}'.`,
    );
  }
  const networks = await docker([
    "inspect",
    "--format",
    "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}",
    app,
  ]);
  return networks.split(" ")[0];
}

const metricsFor = (monitors, status = 1) =>
  monitors
    .map((name) => `monitor_status{monitor_name="${name}"} ${status}`)
    .join("\n");

// Reads the request headers, then answers with the current metrics file or a 401.
const HANDLER = `ok=0
while IFS= read -r l; do
  l=$(printf %s "$l" | tr -d "\\r")
  [ -z "$l" ] && break
  [ "$l" = "Authorization: Basic $AUTH" ] && ok=1
done
if [ $ok = 1 ]; then
  printf "HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nConnection: close\\r\\n\\r\\n"
  cat /tmp/metrics
else
  printf "HTTP/1.1 401 Unauthorized\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n"
fi`;

// Atomic replace, so a request never reads a half-written file.
const setMonitorStatus = (fakeName, monitors, status) =>
  docker([
    "exec",
    fakeName,
    "sh",
    "-c",
    'printf "%s\\n" "$0" > /tmp/metrics.new && mv /tmp/metrics.new /tmp/metrics',
    metricsFor(monitors, status),
  ]);

async function startFakeUptimeKuma({ name, runId, network, monitors }) {
  await startContainer({
    name,
    runId,
    options: [
      "--network",
      network,
      "-e",
      `METRICS=${metricsFor(monitors)}`,
      "-e",
      `AUTH=${Buffer.from(`:${API_KEY}`).toString("base64")}`,
      "-e",
      `HANDLER=${HANDLER}`,
    ],
    // Busybox in this image has no httpd; `nc -ll` runs the handler for every
    // connection, however often the app asks.
    command: [
      "sh",
      "-c",
      'printf "%s\\n" "$METRICS" > /tmp/metrics; exec nc -ll -p 8080 -e sh -c "$HANDLER"',
    ],
  });
  const ip = await docker([
    "inspect",
    "--format",
    `{{(index .NetworkSettings.Networks "${network}").IPAddress}}`,
    name,
  ]);
  // An empty or "invalid IP" address means the server container did not start.
  expect(ip, `${name} should have an address on ${network}`).toMatch(/^\d+\./);
  return `http://${ip}:8080`;
}

const mappingsTable = (page) =>
  page.getByRole("table").filter({
    has: page.getByRole("columnheader", { name: "Type" }),
  });

test(
  "re-enabling Uptime-Kuma keeps a manual mapping and refreshes the auto mappings",
  { tag: ["@configuration", "@regression"] },
  async ({ page, request, baseURL, createContainer }) => {
    // Two full enable cycles through the UI, with modals and alerts in between.
    test.setTimeout(90000);
    const current = await request.get("/api/config");
    expect(current.ok()).toBeTruthy();
    const config = await current.json();
    // The test disables the integration at the end, which stops the app's monitor and
    // is not undone by restoring the configuration, so leave an instance that already
    // uses Uptime-Kuma alone.
    test.skip(
      config.uptime_kuma.enabled,
      "Uptime-Kuma is already enabled on this instance",
    );
    const manualContainer = await createContainer({ suffix: "kuma-manual" });
    const autoContainer = await createContainer({ suffix: "kuma-auto" });
    // Auto-mapping matches a container to the monitor with its name. The manual
    // container's own name is a monitor too, so enabling offers it a conflicting
    // auto mapping that the manual mapping has to win over.
    const manualMonitor = "E2E manual target";
    const fakeName = `${manualContainer}-kuma`;
    const kumaUrl = await startFakeUptimeKuma({
      name: fakeName,
      runId: process.env.UI_E2E_RUN_ID,
      network: await appNetwork(baseURL),
      monitors: [manualContainer, autoContainer, manualMonitor],
    });

    try {
      // Start from a disabled integration with no mappings.
      config.uptime_kuma_mappings = [];
      expect((await request.put("/api/config", { data: config })).ok()).toBe(
        true,
      );

      const enable = async () => {
        await page.goto("/config");
        await page.getByPlaceholder("http://localhost:3001").fill(kumaUrl);
        await page.getByPlaceholder(/Enter your API key/).fill(API_KEY);
        // The checkbox label is not linked to the input (see #482), so find it by role
        // inside the connection form.
        await page
          .locator("form")
          .filter({ has: page.getByPlaceholder("http://localhost:3001") })
          .getByRole("checkbox")
          .uncheck();
        await page.getByRole("button", { name: "Test Connection" }).click();
        await page.getByRole("button", { name: "Enable Integration" }).click();
        await expect(page.getByText("Integration enabled!")).toBeVisible();
      };

      await enable();
      const table = mappingsTable(page);
      const manualRow = table.getByRole("row", { name: manualContainer });
      const autoRow = table.getByRole("row", { name: autoContainer });
      await expect(manualRow).toContainText("Auto");
      await expect(autoRow).toContainText("Auto");

      // Replace the manual container's auto mapping with a manual one.
      await manualRow.getByRole("button", { name: "Delete" }).click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Delete Mapping" })
        .click();
      await expect(manualRow).toBeHidden();
      await page
        .getByRole("combobox")
        .filter({
          has: page.getByRole("option", { name: "Select Container..." }),
        })
        .selectOption({ label: `${manualContainer} (running)` });
      await page
        .getByRole("combobox")
        .filter({
          has: page.getByRole("option", { name: "Select Monitor..." }),
        })
        .selectOption(manualMonitor);
      await page.getByRole("button", { name: "Add", exact: true }).click();
      await expect(manualRow).toContainText("Manual");
      await expect(manualRow).toContainText(manualMonitor);

      // Disable keeps the mappings; enabling again is what used to discard them (#324).
      await page.getByRole("button", { name: "Disable Integration" }).click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Disable Integration" })
        .click();
      await expect(
        page.getByText("Integration disabled successfully"),
      ).toBeVisible();
      await enable();

      await expect(manualRow).toContainText("Manual");
      await expect(manualRow).toContainText(manualMonitor);
      await expect(autoRow).toContainText("Auto");

      // The persisted state matches: one manual mapping that beat the conflicting
      // auto mapping, and the container without one is auto-mapped again.
      const response = await request.get("/api/uptime-kuma/mappings");
      expect(response.ok()).toBeTruthy();
      const { mappings } = await response.json();
      const byContainer = (id) => mappings.filter((m) => m.container_id === id);
      expect(byContainer(manualContainer)).toEqual([
        {
          container_id: manualContainer,
          monitor_friendly_name: manualMonitor,
          auto_mapped: false,
        },
      ]);
      expect(byContainer(autoContainer)).toEqual([
        {
          container_id: autoContainer,
          monitor_friendly_name: autoContainer,
          auto_mapped: true,
        },
      ]);
    } finally {
      await request.post("/api/uptime-kuma/disable");
      await removeNamed([fakeName]);
    }
  },
);

const dockerState = async (name) => {
  const [id, startedAt, running, health] = (
    await inspectContainer(
      name,
      "{{.Id}} {{.State.StartedAt}} {{.State.Running}} {{.State.Health.Status}}",
    )
  ).split(" ");
  return { id, startedAt, running: running === "true", health };
};

const healthyOptions = ["--health-cmd", "true", "--health-interval", "1s"];

test(
  "a DOWN monitor restarts only its mapped container, and recovery to UP does not restart it again",
  { tag: ["@monitoring", "@regression"] },
  async ({ request, baseURL, createContainer }) => {
    test.setTimeout(240000);
    const intervalSeconds = 2;
    const config = await (await request.get("/api/config")).json();
    // The test disables the integration at the end, so it must not run on an instance
    // that already uses Uptime-Kuma.
    expect(
      config.uptime_kuma.enabled,
      "Uptime-Kuma is already enabled on this instance",
    ).toBe(false);

    const mapped = await createContainer({
      suffix: "kuma-down",
      monitored: true,
      options: healthyOptions,
    });
    const sibling = await createContainer({
      suffix: "kuma-sibling",
      monitored: true,
      options: healthyOptions,
    });
    const monitor = `E2E down target ${mapped}`;
    const fakeName = `${mapped}-kuma`;

    const restartEvents = async (name) => {
      const response = await request.get("/api/events", {
        params: { event_type: "restart", container: name, limit: 1000 },
      });
      expect(response.ok()).toBeTruthy();
      return response.json();
    };
    // Event timestamps come from the app's clock, so the watermark is the newest
    // matching event the app has already logged, not the test runner's time.
    const watermark = async (name) =>
      (await restartEvents(name))
        .map((e) => e.timestamp)
        .sort()
        .at(-1) ?? "";
    const restartsAfter = async (name, mark) =>
      (await restartEvents(name)).filter((e) => e.timestamp > mark);
    const monitorStatus = async () => {
      const response = await request.get("/api/containers");
      expect(response.ok()).toBeTruthy();
      const found = (await response.json()).find((c) => c.name === mapped);
      return found?.uptime_kuma_status;
    };
    const waitHealthy = (name) =>
      expect
        .poll(
          async () => {
            const s = await dockerState(name).catch(() => ({}));
            return s.running && s.health === "healthy";
          },
          { timeout: 60000 },
        )
        .toBe(true);

    try {
      await waitHealthy(mapped);
      await waitHealthy(sibling);
      const before = await dockerState(mapped);
      const siblingBefore = await dockerState(sibling);
      expect(before.running).toBe(true);
      expect(before.health).toBe("healthy");

      const kumaUrl = await startFakeUptimeKuma({
        name: fakeName,
        runId: process.env.UI_E2E_RUN_ID,
        network: await appNetwork(baseURL),
        monitors: [monitor],
      });

      // One interval setting drives both the Uptime-Kuma poll and the engine.
      expect(
        (
          await request.put("/api/config/monitor", {
            data: { ...config.monitor, interval_seconds: intervalSeconds },
          })
        ).ok(),
      ).toBeTruthy();
      // The default 60 s cooldown and 10 s backoff would suppress a second restart
      // during the recovery window and let that assertion pass for the wrong reason.
      expect(
        (
          await request.put("/api/config/restart", {
            data: {
              ...config.restart,
              cooldown_seconds: 0,
              max_restarts: 100,
              backoff: { ...config.restart.backoff, enabled: false },
            },
          })
        ).ok(),
      ).toBeTruthy();
      const enabled = await request.post("/api/uptime-kuma/enable", {
        data: {
          server_url: kumaUrl,
          api_token: API_KEY,
          auto_restart_on_down: true,
        },
      });
      expect(enabled.ok()).toBeTruthy();
      const mapping = await request.post("/api/uptime-kuma/mappings", {
        data: { container_id: mapped, monitor_friendly_name: monitor },
      });
      expect(mapping.ok()).toBeTruthy();
      await expect.poll(monitorStatus, { timeout: 30000 }).toBe(1);

      // 1. DOWN restarts the mapped container.
      const downMark = await watermark(mapped);
      const siblingMark = await watermark(sibling);
      await setMonitorStatus(fakeName, [monitor], 0);
      await expect
        .poll(
          async () =>
            (await restartsAfter(mapped, downMark)).find(
              (e) => e.status === "success",
            ),
          { timeout: 60000 },
        )
        .toMatchObject({
          event_type: "restart",
          container_id: before.id,
          // The engine appends the recovery identifier, which is the name here.
          container_name: `${mapped} (${mapped})`,
          status: "success",
          message: expect.stringContaining(RESTART_REASON),
        });
      await expect
        .poll(async () => (await dockerState(mapped)).startedAt, {
          timeout: 60000,
        })
        .not.toBe(before.startedAt);
      await waitHealthy(mapped);
      expect((await dockerState(mapped)).id).toBe(before.id);

      // 2. Recovery: the app has processed UP, then nothing restarts the container.
      await setMonitorStatus(fakeName, [monitor], 1);
      await expect.poll(monitorStatus, { timeout: 30000 }).toBe(1);
      await waitHealthy(mapped);
      const upState = await dockerState(mapped);
      const upMark = await watermark(mapped);
      const deadline = Date.now() + 3 * intervalSeconds * 1000;
      do {
        expect((await dockerState(mapped)).startedAt).toBe(upState.startedAt);
        expect(await restartsAfter(mapped, upMark)).toEqual([]);
        await new Promise((resolve) => setTimeout(resolve, 500));
      } while (Date.now() < deadline);

      // 3. The unmapped sibling was never touched.
      expect((await dockerState(sibling)).startedAt).toBe(
        siblingBefore.startedAt,
      );
      expect(await restartsAfter(sibling, siblingMark)).toEqual([]);
    } finally {
      // Disable first so the monitor task stops before its endpoint disappears, then
      // restore the configuration; a failure in one step must not skip the rest.
      await request.post("/api/uptime-kuma/disable").catch(() => {});
      await request.put("/api/config", { data: config }).catch(() => {});
      await removeNamed([fakeName]).catch(() => {});
    }
  },
);
