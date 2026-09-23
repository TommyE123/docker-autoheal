import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../services/api", () => ({
  getContainers: vi.fn(),
  updateContainerSelection: vi.fn(),
  restartContainer: vi.fn(),
  unquarantineContainer: vi.fn(),
  getContainerDetails: vi.fn(),
}));

import { getContainers, restartContainer } from "../services/api";
import ContainersPage from "./ContainersPage";

const containers = [
  {
    id: "abc123",
    name: "web-app",
    image: "nginx:latest",
    status: "running",
    health: null,
    monitored: true,
    quarantined: false,
    restart_count: 0,
    uptime_kuma_status: null,
    uptime_kuma_monitor_name: null,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ContainersPage", () => {
  it('shows a "no containers" message when none are returned', async () => {
    getContainers.mockResolvedValue({ data: [] });

    render(<ContainersPage />);

    expect(await screen.findByText(/no containers found/i)).toBeInTheDocument();
  });

  it("lists fetched containers with their name and status", async () => {
    getContainers.mockResolvedValue({ data: containers });

    render(<ContainersPage />);

    expect(await screen.findByText("web-app")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("restarts a container after confirming the restart action", async () => {
    const user = userEvent.setup();
    getContainers.mockResolvedValue({ data: containers });
    restartContainer.mockResolvedValue({});

    render(<ContainersPage />);

    await screen.findByText("web-app");

    await user.click(screen.getByRole("button", { name: /restart/i }));
    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() =>
      expect(restartContainer).toHaveBeenCalledWith("abc123"),
    );
  });
});
