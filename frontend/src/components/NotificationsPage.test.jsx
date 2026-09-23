import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../services/api", () => ({
  getNotificationsConfig: vi.fn(),
  updateNotificationsConfig: vi.fn(),
  addNotificationService: vi.fn(),
  updateNotificationService: vi.fn(),
  deleteNotificationService: vi.fn(),
  testNotificationService: vi.fn(),
}));

import {
  getNotificationsConfig,
  updateNotificationsConfig,
} from "../services/api";
import NotificationsPage from "./NotificationsPage";

const config = {
  enabled: false,
  event_filters: [],
  services: [],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NotificationsPage", () => {
  it("shows the current enabled/disabled state after loading", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    expect(
      await screen.findByText(/notifications are disabled/i),
    ).toBeInTheDocument();
  });

  it("toggles notifications on when the switch is clicked", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    updateNotificationsConfig.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("checkbox"));

    await waitFor(() =>
      expect(updateNotificationsConfig).toHaveBeenCalledWith({ enabled: true }),
    );
  });

  it("shows a message when no notification services are configured", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    expect(
      await screen.findByText(/no notification services configured/i),
    ).toBeInTheDocument();
  });
});
