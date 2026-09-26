import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../services/api", () => ({
  getConfig: vi.fn(),
  updateMonitorConfig: vi.fn(),
  updateRestartConfig: vi.fn(),
  updateObservabilityConfig: vi.fn(),
  exportConfig: vi.fn(),
  importConfig: vi.fn(),
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

import {
  getConfig,
  updateMonitorConfig,
  updateRestartConfig,
  updateObservabilityConfig,
  exportConfig,
  importConfig,
} from "../services/api";
import api from "../services/api";
import ConfigPage from "./ConfigPage";

const config = {
  monitor: {
    interval_seconds: 30,
    label_key: "autoheal",
    label_value: "true",
    include_all: false,
  },
  restart: {
    mode: "on-failure",
    cooldown_seconds: 10,
    max_restarts: 3,
    max_restarts_window_seconds: 300,
    respect_manual_stop: true,
    backoff: { enabled: false, initial_seconds: 5, multiplier: 2 },
  },
  observability: { log_level: "INFO", prometheus_enabled: false },
  uptime_kuma: { enabled: false },
};

// Uptime Kuma form is pre-filled so "Test Connection" is enabled without typing.
const kumaReadyConfig = {
  ...config,
  uptime_kuma: {
    enabled: false,
    server_url: "http://kuma.local",
    api_token: "tok123",
    username: "",
    auto_restart_on_down: true,
  },
};

const kumaEnabledConfig = {
  ...config,
  uptime_kuma: {
    enabled: true,
    server_url: "http://kuma.local",
    api_token: "tok123",
    username: "",
    auto_restart_on_down: true,
  },
};

const containers = [{ id: "abc123", name: "web-app", status: "running" }];
const monitors = [{ friendly_name: "web-monitor", status: 1 }];
const mappings = [
  { container_id: "abc123", monitor_friendly_name: "web-monitor", auto_mapped: false },
];

function mockKumaGets({ monitors: m = [], mappings: mp = [], containers: c = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url === "/uptime-kuma/monitors") return Promise.resolve({ data: { monitors: m } });
    if (url === "/uptime-kuma/mappings") return Promise.resolve({ data: { mappings: mp } });
    if (url === "/containers") return Promise.resolve({ data: c });
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConfigPage", () => {
  it("renders monitor settings loaded from the API", async () => {
    getConfig.mockResolvedValue({ data: config });

    render(<ConfigPage />);

    expect(await screen.findByText("Monitor Settings")).toBeInTheDocument();
    expect(screen.getByText("Restart Policy")).toBeInTheDocument();
  });

  it("does not show the misleading 'stored in memory' persistence note (issue #133)", async () => {
    getConfig.mockResolvedValue({ data: config });

    render(<ConfigPage />);

    await screen.findByText("Monitor Settings");

    expect(screen.queryByText(/stored in memory/i)).not.toBeInTheDocument();
  });

  it("shows a validation modal instead of saving when the restart window is too small", async () => {
    const user = userEvent.setup();
    const invalidConfig = {
      ...config,
      restart: { ...config.restart, max_restarts_window_seconds: 5 },
    };
    getConfig.mockResolvedValue({ data: invalidConfig });

    render(<ConfigPage />);

    await screen.findByText("Monitor Settings");

    await user.click(
      screen.getByRole("button", { name: /save monitor settings/i }),
    );

    expect(
      await screen.findByText(/invalid monitor settings configuration/i),
    ).toBeInTheDocument();
    expect(updateMonitorConfig).not.toHaveBeenCalled();
  });

  it("saves monitor settings when the timing configuration is valid", async () => {
    const user = userEvent.setup();
    getConfig.mockResolvedValue({ data: config });
    updateMonitorConfig.mockResolvedValue({});

    render(<ConfigPage />);

    await screen.findByText("Monitor Settings");

    await user.click(
      screen.getByRole("button", { name: /save monitor settings/i }),
    );

    await waitForCalled(updateMonitorConfig, config.monitor);
  });

  describe("initial load", () => {
    it("shows a loading spinner before the configuration request settles", () => {
      getConfig.mockReturnValue(new Promise(() => {}));

      render(<ConfigPage />);

      expect(screen.getByText(/loading configuration/i)).toBeInTheDocument();
    });

    it("shows a failure message when the initial configuration request rejects", async () => {
      getConfig.mockRejectedValue(new Error("network down"));

      render(<ConfigPage />);

      expect(
        await screen.findByText(/failed to load configuration/i),
      ).toBeInTheDocument();
    });

    it("shows a failure message when there is no configuration to display", async () => {
      getConfig.mockResolvedValue({ data: null });

      render(<ConfigPage />);

      expect(
        await screen.findByText(/failed to load configuration/i),
      ).toBeInTheDocument();
    });
  });

  describe("monitor settings", () => {
    it("shows an alert when saving monitor settings fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      updateMonitorConfig.mockRejectedValue(new Error("boom"));

      render(<ConfigPage />);
      await screen.findByText("Monitor Settings");

      await user.click(
        screen.getByRole("button", { name: /save monitor settings/i }),
      );

      expect(
        await screen.findByText(/failed to update monitor configuration/i),
      ).toBeInTheDocument();
    });
  });

  describe("restart policy", () => {
    it("shows an alert when saving the restart policy fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      updateRestartConfig.mockRejectedValue(new Error("boom"));

      render(<ConfigPage />);
      await screen.findByText("Restart Policy");

      await user.click(
        screen.getByRole("button", { name: /save restart policy/i }),
      );

      expect(
        await screen.findByText(/failed to update restart policy/i),
      ).toBeInTheDocument();
      expect(updateRestartConfig).toHaveBeenCalledWith(config.restart);
    });
  });

  describe("observability settings", () => {
    it("shows a success alert and refreshes the configuration when saving succeeds", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      updateObservabilityConfig.mockResolvedValue({});

      render(<ConfigPage />);
      await screen.findByText(/configuration export\/import/i);

      await user.click(
        screen.getByRole("button", { name: /save observability settings/i }),
      );

      expect(
        await screen.findByText(/settings saved successfully! log level changed to info/i),
      ).toBeInTheDocument();
      await waitForCalledTimes(getConfig, 2);
    });

    it("shows an alert when saving observability settings fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      updateObservabilityConfig.mockRejectedValue(new Error("boom"));

      render(<ConfigPage />);
      await screen.findByText(/configuration export\/import/i);

      await user.click(
        screen.getByRole("button", { name: /save observability settings/i }),
      );

      expect(
        await screen.findByText(/failed to update observability settings\. please try again\./i),
      ).toBeInTheDocument();
    });
  });

  describe("configuration export", () => {
    beforeEach(() => {
      window.URL.createObjectURL = vi.fn(() => "blob:mock-url");
      window.URL.revokeObjectURL = vi.fn();
    });

    it("shows a success alert when export succeeds", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      exportConfig.mockResolvedValue({ data: config });

      render(<ConfigPage />);
      await screen.findByText(/configuration export\/import/i);

      await user.click(
        screen.getByRole("button", { name: /export configuration/i }),
      );

      expect(
        await screen.findByText(/configuration exported successfully/i),
      ).toBeInTheDocument();
      expect(window.URL.createObjectURL).toHaveBeenCalled();
    });

    it("shows an alert when export fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      exportConfig.mockRejectedValue(new Error("boom"));

      render(<ConfigPage />);
      await screen.findByText(/configuration export\/import/i);

      await user.click(
        screen.getByRole("button", { name: /export configuration/i }),
      );

      expect(
        await screen.findByText(/failed to export configuration/i),
      ).toBeInTheDocument();
    });
  });

  describe("configuration import", () => {
    const importFile = new File(["{}"], "config.json", { type: "application/json" });

    it("shows a success alert and refreshes the configuration when import succeeds", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      importConfig.mockResolvedValue({});

      const { container } = render(<ConfigPage />);
      await screen.findByText(/configuration export\/import/i);

      const fileInput = container.querySelector("#importFile");
      await user.upload(fileInput, importFile);

      expect(
        await screen.findByText(/configuration imported successfully/i),
      ).toBeInTheDocument();
      await waitForCalledTimes(getConfig, 2);
    });

    it("shows an alert when import fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: config });
      importConfig.mockRejectedValue(new Error("boom"));

      const { container } = render(<ConfigPage />);
      await screen.findByText(/configuration export\/import/i);

      const fileInput = container.querySelector("#importFile");
      await user.upload(fileInput, importFile);

      expect(
        await screen.findByText(/failed to import configuration/i),
      ).toBeInTheDocument();
    });
  });

  describe("uptime kuma connection test", () => {
    it("shows a success alert when the connection test succeeds", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaReadyConfig });
      api.post.mockResolvedValue({ data: { success: true, monitor_count: 5 } });

      render(<ConfigPage />);
      await screen.findByRole("button", { name: /test connection/i });

      await user.click(screen.getByRole("button", { name: /test connection/i }));

      expect(
        await screen.findByText(/connection successful! found 5 monitors\./i),
      ).toBeInTheDocument();
      expect(api.post).toHaveBeenCalledWith(
        "/uptime-kuma/test-connection",
        expect.objectContaining({ server_url: "http://kuma.local", api_token: "tok123" }),
      );
    });

    it("shows the server-reported message when the connection is rejected", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaReadyConfig });
      api.post.mockResolvedValue({ data: { success: false, message: "Invalid API key" } });

      render(<ConfigPage />);
      await screen.findByRole("button", { name: /test connection/i });

      await user.click(screen.getByRole("button", { name: /test connection/i }));

      expect(await screen.findByText(/invalid api key/i)).toBeInTheDocument();
    });

    it("shows an alert when the connection test request errors", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaReadyConfig });
      api.post.mockRejectedValue(new Error("Network Error"));

      render(<ConfigPage />);
      await screen.findByRole("button", { name: /test connection/i });

      await user.click(screen.getByRole("button", { name: /test connection/i }));

      expect(
        await screen.findByText(/connection failed: network error/i),
      ).toBeInTheDocument();
    });
  });

  describe("uptime kuma enable", () => {
    it("shows a success alert and refreshes the configuration when enabling succeeds", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaReadyConfig });
      api.post.mockImplementation((url) => {
        if (url === "/uptime-kuma/test-connection") {
          return Promise.resolve({ data: { success: true, monitor_count: 2 } });
        }
        if (url === "/uptime-kuma/enable") {
          return Promise.resolve({
            data: { success: true, monitors, auto_mappings: mappings },
          });
        }
        return Promise.reject(new Error(`Unexpected POST ${url}`));
      });

      render(<ConfigPage />);
      await screen.findByRole("button", { name: /test connection/i });
      await user.click(screen.getByRole("button", { name: /test connection/i }));
      await screen.findByRole("button", { name: /enable integration/i });

      await user.click(screen.getByRole("button", { name: /enable integration/i }));

      expect(
        await screen.findByText(/integration enabled! 1 auto-mappings created\./i),
      ).toBeInTheDocument();
      await waitForCalledTimes(getConfig, 2);
    });

    it("shows an alert when enabling the integration fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaReadyConfig });
      api.post.mockImplementation((url) => {
        if (url === "/uptime-kuma/test-connection") {
          return Promise.resolve({ data: { success: true, monitor_count: 2 } });
        }
        if (url === "/uptime-kuma/enable") {
          return Promise.reject(new Error("Server error"));
        }
        return Promise.reject(new Error(`Unexpected POST ${url}`));
      });

      render(<ConfigPage />);
      await screen.findByRole("button", { name: /test connection/i });
      await user.click(screen.getByRole("button", { name: /test connection/i }));
      await screen.findByRole("button", { name: /enable integration/i });

      await user.click(screen.getByRole("button", { name: /enable integration/i }));

      expect(
        await screen.findByText(/failed to enable integration: server error/i),
      ).toBeInTheDocument();
    });
  });

  describe("uptime kuma disable", () => {
    it("cancelling the confirmation modal does not disable the integration", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings, containers });

      render(<ConfigPage />);
      await screen.findByText("Active");

      await user.click(screen.getByRole("button", { name: /disable integration/i }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(api.post).not.toHaveBeenCalledWith("/uptime-kuma/disable");
    });

    it("shows a success alert and refreshes the configuration when disabling succeeds", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings, containers });
      api.post.mockResolvedValue({});

      render(<ConfigPage />);
      await screen.findByText("Active");

      await user.click(screen.getByRole("button", { name: /disable integration/i }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /disable integration/i }));

      expect(
        await screen.findByText(/integration disabled successfully/i),
      ).toBeInTheDocument();
      expect(api.post).toHaveBeenCalledWith("/uptime-kuma/disable");
      await waitForCalledTimes(getConfig, 2);
    });

    it("shows an alert when disabling the integration fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings, containers });
      api.post.mockRejectedValue(new Error("Server error"));

      render(<ConfigPage />);
      await screen.findByText("Active");

      await user.click(screen.getByRole("button", { name: /disable integration/i }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /disable integration/i }));

      expect(
        await screen.findByText(/failed to disable integration: server error/i),
      ).toBeInTheDocument();
    });
  });

  describe("uptime kuma mappings", () => {
    it("adds a mapping and refreshes the Uptime Kuma data on success", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings: [], containers });
      api.post.mockResolvedValue({});

      render(<ConfigPage />);
      await screen.findByText("Active");

      const mappingsCard = screen
        .getByText("Container-Monitor Mappings")
        .closest(".card");
      const [containerSelect, monitorSelect] = within(mappingsCard).getAllByRole("combobox");
      await user.selectOptions(containerSelect, "abc123");
      await user.selectOptions(monitorSelect, "web-monitor");
      await user.click(within(mappingsCard).getByRole("button", { name: /^add$/i }));

      expect(
        await screen.findByText(/mapping added successfully!/i),
      ).toBeInTheDocument();
      expect(api.post).toHaveBeenCalledWith("/uptime-kuma/mappings", {
        container_id: "abc123",
        monitor_friendly_name: "web-monitor",
      });
    });

    it("shows an alert when adding a mapping fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings: [], containers });
      api.post.mockRejectedValue(new Error("Server error"));

      render(<ConfigPage />);
      await screen.findByText("Active");

      const mappingsCard = screen
        .getByText("Container-Monitor Mappings")
        .closest(".card");
      const [containerSelect, monitorSelect] = within(mappingsCard).getAllByRole("combobox");
      await user.selectOptions(containerSelect, "abc123");
      await user.selectOptions(monitorSelect, "web-monitor");
      await user.click(within(mappingsCard).getByRole("button", { name: /^add$/i }));

      expect(
        await screen.findByText(/failed to add mapping: server error/i),
      ).toBeInTheDocument();
    });

    it("cancelling the delete confirmation modal keeps the mapping", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings, containers });

      render(<ConfigPage />);
      await screen.findByText("Active");

      await user.click(screen.getByRole("button", { name: /^delete$/i }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(api.delete).not.toHaveBeenCalled();
    });

    it("deletes a mapping and refreshes the Uptime Kuma data on success", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings, containers });
      api.delete.mockResolvedValue({});

      render(<ConfigPage />);
      await screen.findByText("Active");

      await user.click(screen.getByRole("button", { name: /^delete$/i }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /delete mapping/i }));

      expect(await screen.findByText(/mapping deleted!/i)).toBeInTheDocument();
      expect(api.delete).toHaveBeenCalledWith("/uptime-kuma/mappings/abc123");
    });

    it("shows an alert when deleting a mapping fails", async () => {
      const user = userEvent.setup();
      getConfig.mockResolvedValue({ data: kumaEnabledConfig });
      mockKumaGets({ monitors, mappings, containers });
      api.delete.mockRejectedValue(new Error("Server error"));

      render(<ConfigPage />);
      await screen.findByText("Active");

      await user.click(screen.getByRole("button", { name: /^delete$/i }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /delete mapping/i }));

      expect(
        await screen.findByText(/failed to delete mapping: server error/i),
      ).toBeInTheDocument();
    });
  });
});

// Small helpers kept local to this file: waitFor wrappers scoped to a specific
// mock call/call-count instead of arbitrary timing-based waits.
async function waitForCalled(mockFn, ...args) {
  await waitFor(() => expect(mockFn).toHaveBeenCalledWith(...args));
}

async function waitForCalledTimes(mockFn, times) {
  await waitFor(() => expect(mockFn).toHaveBeenCalledTimes(times));
}
