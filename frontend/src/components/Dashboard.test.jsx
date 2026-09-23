import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "./Dashboard";

const systemStatus = {
  total_containers: 10,
  monitored_containers: 7,
  quarantined_containers: 1,
  monitoring_active: true,
  maintenance_mode: false,
};

describe("Dashboard", () => {
  it("displays the metrics from systemStatus", () => {
    render(
      <Dashboard
        systemStatus={systemStatus}
        onRefresh={vi.fn()}
        onMaintenanceToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("calls onRefresh when the refresh button is clicked", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();

    render(
      <Dashboard
        systemStatus={systemStatus}
        onRefresh={onRefresh}
        onMaintenanceToggle={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /refresh/i }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('shows "Enter Maintenance Mode" when not in maintenance and toggles it on click', async () => {
    const user = userEvent.setup();
    const onMaintenanceToggle = vi.fn();

    render(
      <Dashboard
        systemStatus={systemStatus}
        onRefresh={vi.fn()}
        onMaintenanceToggle={onMaintenanceToggle}
      />,
    );

    const toggleButton = screen.getByRole("button", {
      name: /enter maintenance mode/i,
    });
    await user.click(toggleButton);

    expect(onMaintenanceToggle).toHaveBeenCalledTimes(1);
  });

  it('shows "Exit Maintenance" when already in maintenance mode', () => {
    render(
      <Dashboard
        systemStatus={{ ...systemStatus, maintenance_mode: true }}
        onRefresh={vi.fn()}
        onMaintenanceToggle={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /exit maintenance/i }),
    ).toBeInTheDocument();
  });
});
