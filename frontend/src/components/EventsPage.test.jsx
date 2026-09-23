import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../services/api", () => ({
  getEvents: vi.fn(),
  clearEvents: vi.fn(),
}));

import { getEvents, clearEvents } from "../services/api";
import EventsPage from "./EventsPage";

const sampleEvents = [
  {
    container_id: "abc123",
    container_name: "web-app",
    event_type: "restart",
    status: "success",
    message: "Container restarted",
    restart_count: 1,
    timestamp: "2024-01-01T00:00:00Z",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("EventsPage", () => {
  it('shows a "no events" message when there are none', async () => {
    getEvents.mockResolvedValue({ data: [] });

    render(<EventsPage />);

    expect(
      await screen.findByText(/no events recorded yet/i),
    ).toBeInTheDocument();
  });

  it("renders fetched events with their container name and status", async () => {
    getEvents.mockResolvedValue({ data: sampleEvents });

    render(<EventsPage />);

    expect(await screen.findByText("web-app")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("clears all events after confirming the clear action", async () => {
    const user = userEvent.setup();
    getEvents.mockResolvedValue({ data: sampleEvents });
    clearEvents.mockResolvedValue({});

    render(<EventsPage />);

    await screen.findByText("web-app");

    await user.click(screen.getByRole("button", { name: /clear all/i }));
    await user.click(screen.getByRole("button", { name: /clear all events/i }));

    await waitFor(() => expect(clearEvents).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/no events recorded yet/i)).toBeInTheDocument();
  });
});
