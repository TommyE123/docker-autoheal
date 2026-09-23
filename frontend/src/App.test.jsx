import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./services/api", () => ({
  getSystemStatus: vi.fn(),
  enableMaintenanceMode: vi.fn(),
  disableMaintenanceMode: vi.fn(),
  getContainers: vi.fn().mockResolvedValue({ data: [] }),
  updateContainerSelection: vi.fn(),
  restartContainer: vi.fn(),
  unquarantineContainer: vi.fn(),
  getContainerDetails: vi.fn(),
}));

import { getSystemStatus } from "./services/api";
import App from "./App";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("App", () => {
  it("redirects the root route to /containers and renders the Dashboard once status loads", async () => {
    getSystemStatus.mockResolvedValue({
      data: {
        total_containers: 2,
        monitored_containers: 1,
        quarantined_containers: 0,
        monitoring_active: true,
        docker_connected: true,
        maintenance_mode: false,
      },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Docker Auto-Heal Service")).toBeInTheDocument();
  });

  it("shows the maintenance modal when the backend reports maintenance mode active", async () => {
    getSystemStatus.mockResolvedValue({
      data: {
        total_containers: 2,
        monitored_containers: 1,
        quarantined_containers: 0,
        monitoring_active: true,
        docker_connected: true,
        maintenance_mode: true,
        maintenance_start_time: new Date().toISOString(),
      },
    });

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("Maintenance Mode Active"),
    ).toBeInTheDocument();
  });
});
