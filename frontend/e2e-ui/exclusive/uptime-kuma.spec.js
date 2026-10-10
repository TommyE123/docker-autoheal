import { exclusiveTest as test, expect } from "../fixtures.js";
import { docker, removeNamed, startContainer } from "../docker.js";

// The integration needs an Uptime-Kuma /metrics endpoint. A real server would make the
// suite depend on an external service, so a throwaway container serves a fixed metrics
// file instead. The app calls it from inside its own container, so it joins the network
// the app runs on (the default bridge in CI, the Compose network in development).
// Every monitor is UP and auto-restart is switched off, so Uptime-Kuma can never make
// Autoheal restart anything here.

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

const metricsFor = (monitors) =>
  monitors.map((name) => `monitor_status{monitor_name="${name}"} 1`).join("\n");

async function startFakeUptimeKuma({ name, runId, network, monitors }) {
  await startContainer({
    name,
    runId,
    options: ["--network", network, "-e", `METRICS=${metricsFor(monitors)}`],
    // Busybox in this image has no httpd; `nc -ll` answers every connection with the
    // same metrics, however often the app asks.
    command: [
      "nc",
      "-ll",
      "-p",
      "8080",
      "-e",
      "sh",
      "-c",
      'printf "HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nConnection: close\\r\\n\\r\\n%s\\n" "$METRICS"',
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

test.afterEach(async ({ request }) => {
  // Stops the app's Uptime-Kuma monitor; restoring the configuration alone would not.
  await request.post("/api/uptime-kuma/disable");
});

test(
  "re-enabling Uptime-Kuma keeps a manual mapping and refreshes the auto mappings",
  { tag: ["@configuration", "@regression"] },
  async ({ page, request, baseURL, createContainer }) => {
    // Two full enable cycles through the UI, with modals and alerts in between.
    test.setTimeout(90000);
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
      const current = await request.get("/api/config");
      expect(current.ok()).toBeTruthy();
      const config = await current.json();
      config.uptime_kuma = { ...config.uptime_kuma, enabled: false };
      config.uptime_kuma_mappings = [];
      expect((await request.put("/api/config", { data: config })).ok()).toBe(
        true,
      );

      const enable = async () => {
        await page.goto("/config");
        await page.getByPlaceholder("http://localhost:3001").fill(kumaUrl);
        await page.getByPlaceholder(/Enter your API key/).fill("e2e-key");
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
      await removeNamed([fakeName]);
    }
  },
);
