import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

import {
  getSystemStatus,
  enableMaintenanceMode,
  disableMaintenanceMode,
} from "./services/api";
import App from "./App";

const activeStatus = {
  total_containers: 2,
  monitored_containers: 1,
  quarantined_containers: 0,
  monitoring_active: true,
  docker_connected: true,
  maintenance_mode: false,
};

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

describe("App error, toast and refresh handling", () => {
  let consoleError;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
    delete document.hidden;
  });

  it("logs the failure and renders no dashboard when the status request fails", async () => {
    getSystemStatus.mockRejectedValue(new Error("Network Error"));

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith(
        "Failed to fetch system status:",
        expect.any(Error),
      ),
    );
    await act(async () => {});
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });

  it("recovers from a failed status request on the next refresh", async () => {
    getSystemStatus
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValue({ data: activeStatus });

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith(
        "Failed to fetch system status:",
        expect.any(Error),
      ),
    );
    await act(async () => {});
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();

    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(getSystemStatus).toHaveBeenCalledTimes(2);
  });

  it("shows an error toast when enabling maintenance mode fails, and closes it", async () => {
    getSystemStatus.mockResolvedValue({ data: activeStatus });
    enableMaintenanceMode.mockRejectedValue(new Error("500"));
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: /Enter Maintenance Mode/ }),
    );

    const message = "Failed to toggle maintenance mode. Please try again.";
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalledWith(
      "Failed to toggle maintenance mode:",
      expect.any(Error),
    );

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByText(message)).not.toBeInTheDocument(),
    );
  });

  it("enables maintenance mode and shows the modal when the enter button is pressed", async () => {
    getSystemStatus
      .mockResolvedValueOnce({ data: activeStatus })
      .mockResolvedValue({
        data: {
          ...activeStatus,
          maintenance_mode: true,
          maintenance_start_time: new Date().toISOString(),
        },
      });
    enableMaintenanceMode.mockResolvedValue({});
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: /Enter Maintenance Mode/ }),
    );

    expect(enableMaintenanceMode).toHaveBeenCalledTimes(1);
    expect(disableMaintenanceMode).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Maintenance Mode Active"),
    ).toBeInTheDocument();
  });

  it("disables maintenance mode and closes the modal when its exit button is pressed", async () => {
    const maintenanceStatus = {
      data: {
        ...activeStatus,
        maintenance_mode: true,
        maintenance_start_time: new Date().toISOString(),
      },
    };
    getSystemStatus
      .mockResolvedValueOnce(maintenanceStatus)
      .mockResolvedValue({ data: activeStatus });
    disableMaintenanceMode.mockResolvedValue({});
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: /Exit Maintenance Mode/ }),
    );

    expect(disableMaintenanceMode).toHaveBeenCalledTimes(1);
    expect(enableMaintenanceMode).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.queryByText("Maintenance Mode Active"),
      ).not.toBeInTheDocument(),
    );
  });

  it("refreshes status when the tab becomes visible, but not when it is hidden", async () => {
    getSystemStatus.mockResolvedValue({ data: activeStatus });

    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByText("Dashboard");

    const callsBefore = getSystemStatus.mock.calls.length;

    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(getSystemStatus).toHaveBeenCalledTimes(callsBefore);

    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() =>
      expect(getSystemStatus).toHaveBeenCalledTimes(callsBefore + 1),
    );
  });
});
