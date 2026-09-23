import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { format } from "date-fns";

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

const multipleEvents = [
  {
    container_id: "abc123",
    container_name: "web-app",
    event_type: "restart",
    status: "success",
    message: "Container restarted",
    restart_count: 1,
    timestamp: "2024-01-01T00:00:00Z",
  },
  {
    container_id: "def456",
    container_name: "db",
    event_type: "quarantine",
    status: "quarantined",
    message: "Container quarantined after repeated failures",
    restart_count: 3,
    timestamp: "2024-01-02T12:30:00Z",
  },
  {
    container_id: "ghi789",
    container_name: "cache",
    event_type: "health_check_failed",
    status: "failure",
    message: "Health check failed",
    restart_count: 0,
    timestamp: "2024-01-03T08:15:00Z",
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

  it("logs an error and stops loading when fetching events fails", async () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    getEvents.mockRejectedValue(new Error("network error"));

    render(<EventsPage />);

    expect(
      await screen.findByText(/no events recorded yet/i),
    ).toBeInTheDocument();
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Failed to load events:",
      expect.any(Error),
    );

    consoleErrorSpy.mockRestore();
  });

  it("renders multiple events of different types with their fields and timestamps", async () => {
    getEvents.mockResolvedValue({ data: multipleEvents });

    render(<EventsPage />);

    await screen.findByText("web-app");
    expect(screen.getByText("db")).toBeInTheDocument();
    expect(screen.getByText("cache")).toBeInTheDocument();

    expect(screen.getByText("restart")).toBeInTheDocument();
    expect(screen.getByText("quarantine")).toBeInTheDocument();
    expect(screen.getByText("health_check_failed")).toBeInTheDocument();

    expect(screen.getByText("quarantined")).toBeInTheDocument();
    expect(screen.getByText("failure")).toBeInTheDocument();

    expect(screen.getByText(/health check failed/i)).toBeInTheDocument();
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(screen.getByText("Restarts: 3")).toBeInTheDocument();

    const expectedTimestamp = format(new Date("2024-01-03T08:15:00Z"), "PPpp");
    expect(screen.getByText(expectedTimestamp)).toBeInTheDocument();
  });

  it("cancels clearing events without calling the API", async () => {
    const user = userEvent.setup();
    getEvents.mockResolvedValue({ data: sampleEvents });

    render(<EventsPage />);

    await screen.findByText("web-app");

    await user.click(screen.getByRole("button", { name: /clear all/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(clearEvents).not.toHaveBeenCalled();
    expect(screen.getByText("web-app")).toBeInTheDocument();
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
    expect(
      await screen.findByText(/all events cleared successfully/i),
    ).toBeInTheDocument();
  });

  it("shows an alert and keeps the events when clearing fails", async () => {
    const user = userEvent.setup();
    getEvents.mockResolvedValue({ data: sampleEvents });
    clearEvents.mockRejectedValue(new Error("clear failed"));

    render(<EventsPage />);

    await screen.findByText("web-app");

    await user.click(screen.getByRole("button", { name: /clear all/i }));
    await user.click(screen.getByRole("button", { name: /clear all events/i }));

    expect(
      await screen.findByText(/failed to clear events\. please try again\./i),
    ).toBeInTheDocument();
    expect(screen.getByText("web-app")).toBeInTheDocument();
  });

  it("refetches events when the refresh button is clicked", async () => {
    const user = userEvent.setup();
    getEvents.mockResolvedValue({ data: [] });

    render(<EventsPage />);

    await screen.findByText(/no events recorded yet/i);
    expect(getEvents).toHaveBeenCalledTimes(1);

    getEvents.mockResolvedValue({ data: sampleEvents });

    await user.click(screen.getByRole("button", { name: /refresh/i }));

    await screen.findByText("web-app");
    expect(getEvents).toHaveBeenCalledTimes(2);
  });
});
