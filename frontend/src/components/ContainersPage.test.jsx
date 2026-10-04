import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../services/api", () => ({
  getContainers: vi.fn(),
  updateContainerSelection: vi.fn(),
  restartContainer: vi.fn(),
  unquarantineContainer: vi.fn(),
  getContainerDetails: vi.fn(),
}));

import {
  getContainers,
  updateContainerSelection,
  restartContainer,
  unquarantineContainer,
  getContainerDetails,
} from "../services/api";
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

  describe("loading and refresh", () => {
    it("shows a loading indicator until the first fetch resolves", async () => {
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);

      expect(screen.getByText(/loading containers/i)).toBeInTheDocument();
      expect(await screen.findByText("web-app")).toBeInTheDocument();
      expect(screen.queryByText(/loading containers/i)).not.toBeInTheDocument();
    });

    it("shows an error alert when containers fail to load", async () => {
      getContainers.mockRejectedValue(new Error("boom"));

      render(<ContainersPage />);

      expect(await screen.findByText(/failed to load containers/i)).toBeInTheDocument();
    });

    it("refetches containers when Refresh is clicked", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);
      await screen.findByText("web-app");
      getContainers.mockClear();

      await user.click(screen.getByRole("button", { name: /refresh/i }));

      await waitFor(() => expect(getContainers).toHaveBeenCalledWith(true));
    });

    it("polls every 5 seconds and stops polling on unmount", async () => {
      vi.useFakeTimers();
      try {
        getContainers.mockResolvedValue({ data: containers });

        const { unmount } = render(<ContainersPage />);
        await act(async () => {});
        expect(getContainers).toHaveBeenCalledTimes(1);

        await act(async () => {
          await vi.advanceTimersByTimeAsync(5000);
        });
        expect(getContainers).toHaveBeenCalledTimes(2);

        unmount();
        await vi.advanceTimersByTimeAsync(10000);
        expect(getContainers).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });

    it("refetches when the tab becomes visible but not while hidden", async () => {
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);
      await screen.findByText("web-app");
      getContainers.mockClear();

      const hidden = vi.spyOn(document, "hidden", "get");
      try {
        hidden.mockReturnValue(true);
        document.dispatchEvent(new Event("visibilitychange"));
        expect(getContainers).not.toHaveBeenCalled();

        hidden.mockReturnValue(false);
        document.dispatchEvent(new Event("visibilitychange"));
        await waitFor(() => expect(getContainers).toHaveBeenCalledTimes(1));
      } finally {
        hidden.mockRestore();
      }
    });
  });

  describe("badges", () => {
    it.each([
      ["exited", "danger"],
      ["paused", "warning"],
      ["restarting", "info"],
      ["created", "secondary"],
    ])("renders a %s status badge with the %s variant", async (status, variant) => {
      getContainers.mockResolvedValue({ data: [{ ...containers[0], status }] });

      render(<ContainersPage />);

      expect(await screen.findByText(status)).toHaveClass(`bg-${variant}`);
    });

    it.each([
      ["healthy", "success"],
      ["unhealthy", "danger"],
      ["starting", "warning"],
      ["other", "secondary"],
    ])("renders a %s health badge", async (status, variant) => {
      getContainers.mockResolvedValue({
        data: [{ ...containers[0], health: { status } }],
      });

      render(<ContainersPage />);

      expect(await screen.findByText(status)).toHaveClass(`bg-${variant}`);
    });

    it("shows N/A when a container has no health information", async () => {
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);

      expect(await screen.findByText("N/A")).toBeInTheDocument();
    });

    it.each([
      [0, "Down"],
      [1, "Up"],
      [2, "Pending"],
      [3, "Maintenance"],
      [5, "Disabled"],
      [99, "Unknown"],
    ])("maps Uptime Kuma status %s to %s", async (code, text) => {
      getContainers.mockResolvedValue({
        data: [{ ...containers[0], uptime_kuma_status: code, uptime_kuma_monitor_name: "mon" }],
      });

      render(<ContainersPage />);

      expect(await screen.findByText(text)).toHaveAttribute("title", "mon");
    });

    it("shows Not Mapped when there is no status and no monitor", async () => {
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);

      expect(await screen.findByText("Not Mapped")).toBeInTheDocument();
    });

    it("shows Unknown when a monitor is mapped but its status is unavailable", async () => {
      getContainers.mockResolvedValue({
        data: [{ ...containers[0], uptime_kuma_status: null, uptime_kuma_monitor_name: "mon" }],
      });

      render(<ContainersPage />);

      expect(await screen.findByText("Unknown")).toHaveAttribute("title", "mon");
    });

    it("shows the Quarantined badge only for quarantined containers", async () => {
      getContainers.mockResolvedValue({
        data: [
          containers[0],
          { ...containers[0], id: "q1", name: "quarantined-app", quarantined: true },
        ],
      });

      render(<ContainersPage />);

      await screen.findByText("quarantined-app");
      expect(screen.getAllByText("Quarantined")).toHaveLength(1);
    });
  });

  describe("selection and auto-heal", () => {
    const two = [
      containers[0],
      { ...containers[0], id: "def456", name: "db" },
    ];

    it("disables the auto-heal buttons until a container is selected", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: two });

      render(<ContainersPage />);
      await screen.findByText("web-app");

      const enable = screen.getByRole("button", { name: /enable auto-heal/i });
      const disable = screen.getByRole("button", { name: /disable auto-heal/i });
      expect(enable).toBeDisabled();
      expect(disable).toBeDisabled();

      const [, first] = screen.getAllByRole("checkbox");
      await user.click(first);
      expect(enable).toBeEnabled();
      expect(disable).toBeEnabled();

      await user.click(first);
      expect(enable).toBeDisabled();
    });

    it("selects and clears every container with the header checkbox", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: two });

      render(<ContainersPage />);
      await screen.findByText("web-app");

      const [selectAll, ...rows] = screen.getAllByRole("checkbox");
      await user.click(selectAll);
      rows.forEach((box) => expect(box).toBeChecked());
      expect(selectAll).toBeChecked();

      await user.click(selectAll);
      rows.forEach((box) => expect(box).not.toBeChecked());
    });

    it("enables auto-heal for the selected containers and clears the selection", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: two });
      updateContainerSelection.mockResolvedValue({});

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getAllByRole("checkbox")[0]);
      await user.click(screen.getByRole("button", { name: /enable auto-heal/i }));

      await waitFor(() =>
        expect(updateContainerSelection).toHaveBeenCalledWith(["abc123", "def456"], true),
      );
      expect(await screen.findByText(/enabled auto-heal for 2 container/i)).toBeInTheDocument();
      expect(screen.getAllByRole("checkbox")[0]).not.toBeChecked();
    });

    it("disables auto-heal for the selected containers", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: two });
      updateContainerSelection.mockResolvedValue({});

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getAllByRole("checkbox")[1]);
      await user.click(screen.getByRole("button", { name: /disable auto-heal/i }));

      await waitFor(() =>
        expect(updateContainerSelection).toHaveBeenCalledWith(["abc123"], false),
      );
      expect(await screen.findByText(/disabled auto-heal for 1 container/i)).toBeInTheDocument();
    });

    it.each([
      ["enable", /enable auto-heal/i, /failed to enable auto-heal/i],
      ["disable", /disable auto-heal/i, /failed to disable auto-heal/i],
    ])("shows an error and keeps the selection when %s fails", async (_, button, message) => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: two });
      updateContainerSelection.mockRejectedValue(new Error("nope"));

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getAllByRole("checkbox")[1]);
      await user.click(screen.getByRole("button", { name: button }));

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(screen.getAllByRole("checkbox")[1]).toBeChecked();
    });
  });

  describe("restart and unquarantine", () => {
    const quarantined = [{ ...containers[0], quarantined: true }];

    it("does not restart when the confirmation is cancelled", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getByTitle("Restart"));
      expect(screen.getByText(/restart container "web-app"/i)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^cancel$/i }));

      expect(restartContainer).not.toHaveBeenCalled();
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: /^confirm$/i })).not.toBeInTheDocument(),
      );
    });

    it("shows a success alert after a restart", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });
      restartContainer.mockResolvedValue({});

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getByTitle("Restart"));
      await user.click(screen.getByRole("button", { name: /^confirm$/i }));

      expect(await screen.findByText(/container "web-app" restarted/i)).toBeInTheDocument();
    });

    it("shows an error alert when a restart fails", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });
      restartContainer.mockRejectedValue(new Error("nope"));

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getByTitle("Restart"));
      await user.click(screen.getByRole("button", { name: /^confirm$/i }));

      expect(await screen.findByText(/failed to restart container/i)).toBeInTheDocument();
    });

    it("only offers Unquarantine for quarantined containers", async () => {
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);
      await screen.findByText("web-app");

      expect(screen.queryByTitle("Unquarantine")).not.toBeInTheDocument();
    });

    it("removes a container from quarantine after confirming", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: quarantined });
      unquarantineContainer.mockResolvedValue({});

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getByTitle("Unquarantine"));
      await user.click(screen.getByRole("button", { name: /^confirm$/i }));

      await waitFor(() => expect(unquarantineContainer).toHaveBeenCalledWith("abc123"));
      expect(await screen.findByText(/removed from quarantine/i)).toBeInTheDocument();
    });

    it("shows an error alert when unquarantining fails", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: quarantined });
      unquarantineContainer.mockRejectedValue(new Error("nope"));

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getByTitle("Unquarantine"));
      await user.click(screen.getByRole("button", { name: /^confirm$/i }));

      expect(await screen.findByText(/failed to unquarantine container/i)).toBeInTheDocument();
    });

    it("does not open the details modal when action buttons are clicked", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });

      render(<ContainersPage />);
      await screen.findByText("web-app");

      await user.click(screen.getByTitle("Restart"));
      await user.click(screen.getAllByRole("checkbox")[1]);

      expect(getContainerDetails).not.toHaveBeenCalled();
    });
  });

  describe("container details modal", () => {
    const details = {
      full_id: "abc123full",
      name: "web-app",
      image: "nginx:latest",
      status: "running",
      exit_code: 137,
      restart_count: 2,
      recent_restart_count: 1,
      monitored: true,
      quarantined: false,
      health: { status: "healthy" },
      labels: { autoheal: "true" },
    };

    it("opens the details modal when a row is clicked", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });
      getContainerDetails.mockResolvedValue({ data: details });

      render(<ContainersPage />);
      await user.click(await screen.findByText("web-app"));

      await waitFor(() => expect(getContainerDetails).toHaveBeenCalledWith("abc123"));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("Container Details")).toBeInTheDocument();
      expect(within(dialog).getByText("abc123full")).toBeInTheDocument();
      expect(within(dialog).getByText("Health Status")).toBeInTheDocument();
      expect(within(dialog).getByText(/"autoheal": "true"/)).toBeInTheDocument();
      expect(within(dialog).getByText("Exit Code:").nextSibling).toHaveTextContent("137");
    });

    it("omits the health section when the container has no health data", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });
      getContainerDetails.mockResolvedValue({ data: { ...details, health: null, monitored: false, quarantined: true } });

      render(<ContainersPage />);
      await user.click(await screen.findByText("web-app"));

      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).queryByText("Health Status")).not.toBeInTheDocument();
      expect(within(dialog).getByText("Monitored:").nextSibling).toHaveTextContent("No");
      expect(within(dialog).getByText("Quarantined:").nextSibling).toHaveTextContent("Yes");
    });

    it("shows an error alert when details fail to load", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });
      getContainerDetails.mockRejectedValue(new Error("nope"));

      render(<ContainersPage />);
      await user.click(await screen.findByText("web-app"));

      expect(await screen.findByText(/failed to load container details/i)).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("closes the details modal", async () => {
      const user = userEvent.setup();
      getContainers.mockResolvedValue({ data: containers });
      getContainerDetails.mockResolvedValue({ data: details });

      render(<ContainersPage />);
      await user.click(await screen.findByText("web-app"));
      const dialog = await screen.findByRole("dialog");

      await user.click(within(dialog).getByRole("button", { name: /close/i }));

      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });
  });
});
