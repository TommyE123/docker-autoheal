import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
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
  getApiKey: vi.fn(() => null),
  setApiKey: vi.fn(),
  clearApiKey: vi.fn(),
  onUnauthorized: vi.fn(),
}));

import {
  getSystemStatus,
  getApiKey,
  setApiKey,
  clearApiKey,
  onUnauthorized,
} from "./services/api";
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

  describe("API key prompt", () => {
    const renderApp = async () => {
      getSystemStatus.mockResolvedValue({
        data: {
          total_containers: 0,
          monitored_containers: 0,
          quarantined_containers: 0,
          monitoring_active: true,
          docker_connected: true,
          maintenance_mode: false,
        },
      });
      render(
        <MemoryRouter initialEntries={["/containers"]}>
          <App />
        </MemoryRouter>,
      );
      await screen.findByText("Dashboard");
      return onUnauthorized.mock.calls[0][0];
    };

    it("does not prompt while the API is not asking for a key", async () => {
      await renderApp();

      expect(
        screen.queryByRole("dialog", { name: "API key required" }),
      ).not.toBeInTheDocument();
    });

    it("prompts when the API answers 401", async () => {
      const on401 = await renderApp();

      act(() => on401());

      expect(
        await screen.findByRole("dialog", { name: "API key required" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("says the key was rejected when one was already stored", async () => {
      getApiKey.mockReturnValue("stale");
      const on401 = await renderApp();

      act(() => on401());

      expect(await screen.findByRole("alert")).toHaveTextContent(/rejected/i);
      getApiKey.mockReturnValue(null);
    });

    describe("changing the stored key", () => {
      const originalLocation = window.location;
      const reload = vi.fn();

      beforeEach(() => {
        Object.defineProperty(window, "location", {
          configurable: true,
          value: { ...originalLocation, reload },
        });
      });

      afterEach(() => {
        Object.defineProperty(window, "location", {
          configurable: true,
          value: originalLocation,
        });
        getApiKey.mockReturnValue(null);
      });

      it("stores a submitted key and reloads so every view refetches", async () => {
        const user = userEvent.setup();
        setApiKey.mockReturnValue(true);
        const on401 = await renderApp();
        act(() => on401());

        await user.type(await screen.findByLabelText("API key"), "new-key");
        await user.click(screen.getByRole("button", { name: "Save key" }));

        expect(setApiKey).toHaveBeenCalledWith("new-key");
        expect(reload).toHaveBeenCalled();
      });

      it("keeps working without a reload when the key could not be persisted", async () => {
        const user = userEvent.setup();
        setApiKey.mockReturnValue(false);
        const on401 = await renderApp();
        act(() => on401());
        const callsBefore = getSystemStatus.mock.calls.length;

        await user.type(await screen.findByLabelText("API key"), "mem-key");
        await user.click(screen.getByRole("button", { name: "Save key" }));

        expect(setApiKey).toHaveBeenCalledWith("mem-key");
        expect(reload).not.toHaveBeenCalled();
        await waitFor(() =>
          expect(
            screen.queryByRole("dialog", { name: "API key required" }),
          ).not.toBeInTheDocument(),
        );
        expect(getSystemStatus.mock.calls.length).toBeGreaterThan(callsBefore);
      });

      it("clears the stored key and reloads", async () => {
        const user = userEvent.setup();
        clearApiKey.mockReturnValue(true);
        getApiKey.mockReturnValue("stored");
        const on401 = await renderApp();
        act(() => on401());

        await user.click(
          await screen.findByRole("button", { name: "Clear stored key" }),
        );

        expect(clearApiKey).toHaveBeenCalled();
        expect(reload).toHaveBeenCalled();
      });

      it("does not reload when the key could not be removed from storage", async () => {
        const user = userEvent.setup();
        clearApiKey.mockReturnValue(false);
        getApiKey.mockReturnValue("stored");
        const on401 = await renderApp();
        act(() => on401());
        const callsBefore = getSystemStatus.mock.calls.length;

        await user.click(
          await screen.findByRole("button", { name: "Clear stored key" }),
        );

        expect(clearApiKey).toHaveBeenCalled();
        expect(reload).not.toHaveBeenCalled();
        await waitFor(() =>
          expect(
            screen.queryByRole("dialog", { name: "API key required" }),
          ).not.toBeInTheDocument(),
        );
        expect(getSystemStatus.mock.calls.length).toBeGreaterThan(callsBefore);
      });

      it("reopens the prompt from the navigation item after a cancel", async () => {
        const user = userEvent.setup();
        getApiKey.mockReturnValue("stored");
        const on401 = await renderApp();
        act(() => on401());
        await user.click(await screen.findByRole("button", { name: "Cancel" }));

        await user.click(screen.getByRole("button", { name: /api key/i }));

        expect(
          await screen.findByRole("dialog", { name: "API key required" }),
        ).toBeInTheDocument();
      });
    });

    it("does not re-open the prompt after cancel, even if polling keeps getting 401", async () => {
      const user = userEvent.setup();
      const on401 = await renderApp();
      act(() => on401());
      await user.click(await screen.findByRole("button", { name: "Cancel" }));
      await waitFor(() =>
        expect(
          screen.queryByRole("dialog", { name: "API key required" }),
        ).not.toBeInTheDocument(),
      );

      act(() => on401());

      expect(
        screen.queryByRole("dialog", { name: "API key required" }),
      ).not.toBeInTheDocument();
    });
  });
});
