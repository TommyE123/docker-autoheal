import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

import { getConfig, updateMonitorConfig } from "../services/api";
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

    await waitFor(() =>
      expect(updateMonitorConfig).toHaveBeenCalledWith(config.monitor),
    );
  });
});
