import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { format } from "date-fns";

vi.mock("../services/api", () => ({
  getEvents: vi.fn(),
  clearEvents: vi.fn(),
  getContainers: vi.fn(),
}));

import { getEvents, clearEvents, getContainers } from "../services/api";
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
  getContainers.mockResolvedValue({ data: [] });
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

    expect(screen.getByText("Health check failed")).toBeInTheDocument();
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

  it("clears all events after confirming the clear action, refreshing the list from local state without refetching", async () => {
    const user = userEvent.setup();
    getEvents.mockResolvedValue({ data: sampleEvents });
    clearEvents.mockResolvedValue({});

    render(<EventsPage />);

    await screen.findByText("web-app");
    expect(getEvents).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /clear all/i }));
    await user.click(screen.getByRole("button", { name: /clear all events/i }));

    await waitFor(() => expect(clearEvents).toHaveBeenCalledTimes(1));

    // The component refreshes the list by clearing local state directly,
    // not by calling getEvents() again.
    expect(getEvents).toHaveBeenCalledTimes(1);

    expect(screen.queryByText("web-app")).not.toBeInTheDocument();
    expect(screen.getByText(/no events recorded yet/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/all events cleared successfully/i),
    ).toBeInTheDocument();

    // Clear All is disabled once the list is empty, confirming the
    // rendered state reflects the cleared events, not stale data.
    expect(screen.getByRole("button", { name: /clear all/i })).toBeDisabled();
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

  describe("filters and limit", () => {
    const lastCall = () => getEvents.mock.calls[getEvents.mock.calls.length - 1];

    const renderPage = async () => {
      getEvents.mockResolvedValue({ data: sampleEvents });
      getContainers.mockResolvedValue({
        data: [
          { id: "abc123", name: "web-app" },
          { id: "def456", name: "db" },
        ],
      });
      render(<EventsPage />);
      await screen.findByRole("heading", { name: "web-app" });
      await screen.findByRole("option", { name: "db" });
    };

    it("renders the three controls", async () => {
      await renderPage();

      expect(screen.getByLabelText("Event Type")).toBeInTheDocument();
      expect(screen.getByLabelText("Container")).toBeInTheDocument();
      expect(screen.getByLabelText("Limit")).toBeInTheDocument();
    });

    it("requests limit 50 with no filters by default", async () => {
      await renderPage();

      expect(getEvents).toHaveBeenCalledWith(50, {
        eventType: "",
        container: "",
      });
      expect(
        screen.queryByRole("button", { name: /clear filters/i }),
      ).not.toBeInTheDocument();
    });

    it("sends event_type when an event type is selected and omits it for All", async () => {
      const user = userEvent.setup();
      await renderPage();

      await user.selectOptions(screen.getByLabelText("Event Type"), "quarantine");
      await waitFor(() =>
        expect(lastCall()).toEqual([50, { eventType: "quarantine", container: "" }]),
      );

      await user.selectOptions(screen.getByLabelText("Event Type"), "");
      await waitFor(() =>
        expect(lastCall()).toEqual([50, { eventType: "", container: "" }]),
      );
    });

    it("sends container when a container is selected and omits it for All", async () => {
      const user = userEvent.setup();
      await renderPage();

      await user.selectOptions(screen.getByLabelText("Container"), "db");
      await waitFor(() =>
        expect(lastCall()).toEqual([50, { eventType: "", container: "db" }]),
      );

      await user.selectOptions(screen.getByLabelText("Container"), "");
      await waitFor(() =>
        expect(lastCall()).toEqual([50, { eventType: "", container: "" }]),
      );
    });

    it("sends both filters together", async () => {
      const user = userEvent.setup();
      await renderPage();

      await user.selectOptions(screen.getByLabelText("Event Type"), "restart");
      await user.selectOptions(screen.getByLabelText("Container"), "web-app");

      await waitFor(() =>
        expect(lastCall()).toEqual([
          50,
          { eventType: "restart", container: "web-app" },
        ]),
      );
    });

    it.each([25, 50, 100])("sends limit %i when selected", async (limit) => {
      const user = userEvent.setup();
      await renderPage();

      await user.selectOptions(screen.getByLabelText("Limit"), String(limit));

      await waitFor(() => expect(lastCall()[0]).toBe(limit));
    });

    it("Clear Filters resets filters but keeps the selected limit", async () => {
      const user = userEvent.setup();
      await renderPage();

      await user.selectOptions(screen.getByLabelText("Limit"), "100");
      await user.selectOptions(screen.getByLabelText("Event Type"), "restart");
      await user.selectOptions(screen.getByLabelText("Container"), "db");

      await user.click(screen.getByRole("button", { name: /clear filters/i }));

      expect(screen.getByLabelText("Event Type")).toHaveValue("");
      expect(screen.getByLabelText("Container")).toHaveValue("");
      expect(screen.getByLabelText("Limit")).toHaveValue("100");
      await waitFor(() =>
        expect(lastCall()).toEqual([100, { eventType: "", container: "" }]),
      );
      expect(
        screen.queryByRole("button", { name: /clear filters/i }),
      ).not.toBeInTheDocument();
    });

    it("Refresh preserves the selected controls", async () => {
      const user = userEvent.setup();
      await renderPage();

      await user.selectOptions(screen.getByLabelText("Limit"), "25");
      await user.selectOptions(screen.getByLabelText("Event Type"), "restart");
      await user.selectOptions(screen.getByLabelText("Container"), "db");
      getEvents.mockClear();

      await user.click(screen.getByRole("button", { name: /refresh/i }));

      await waitFor(() =>
        expect(getEvents).toHaveBeenCalledWith(25, {
          eventType: "restart",
          container: "db",
        }),
      );
    });

    it("the 5-second auto-refresh preserves the selected controls", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
        await renderPage();

        await user.selectOptions(screen.getByLabelText("Limit"), "100");
        await user.selectOptions(screen.getByLabelText("Event Type"), "restart");
        await user.selectOptions(screen.getByLabelText("Container"), "db");
        await waitFor(() =>
          expect(lastCall()).toEqual([100, { eventType: "restart", container: "db" }]),
        );

        getEvents.mockClear();
        await vi.advanceTimersByTimeAsync(5000);

        expect(getEvents).toHaveBeenCalledWith(100, {
          eventType: "restart",
          container: "db",
        });
      } finally {
        vi.useRealTimers();
      }
    });

    it("ignores a stale response that resolves after a newer selection's response", async () => {
      const user = userEvent.setup();
      let resolveStale;
      getEvents.mockResolvedValueOnce({ data: [] });
      getContainers.mockResolvedValue({ data: [{ id: "abc123", name: "web-app" }] });
      render(<EventsPage />);
      await screen.findByText(/no events recorded yet/i);

      // Request for the first selection stays pending...
      getEvents.mockImplementationOnce(
        () => new Promise((resolve) => (resolveStale = resolve)),
      );
      await user.selectOptions(screen.getByLabelText("Event Type"), "quarantine");

      // ...while a newer selection resolves first.
      getEvents.mockResolvedValueOnce({ data: sampleEvents });
      await user.selectOptions(screen.getByLabelText("Event Type"), "restart");
      await screen.findByRole("heading", { name: "web-app" });

      await act(async () => {
        resolveStale({ data: multipleEvents });
      });

      expect(screen.getByRole("heading", { name: "web-app" })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "cache" })).not.toBeInTheDocument();
    });

    it("does not filter the returned events client-side", async () => {
      const user = userEvent.setup();
      getEvents.mockResolvedValue({ data: multipleEvents });
      render(<EventsPage />);
      await screen.findByRole("heading", { name: "cache" });

      await user.selectOptions(screen.getByLabelText("Event Type"), "restart");

      // The mocked API still returns all events; the page shows what it gets.
      await waitFor(() => expect(lastCall()[1].eventType).toBe("restart"));
      expect(screen.getByRole("heading", { name: "db" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "cache" })).toBeInTheDocument();
    });
  });

  it("keeps showing the loading state until the latest initial request settles", async () => {
    let resolveFirst;
    let resolveSecond;
    getEvents
      .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
      .mockImplementationOnce(() => new Promise((resolve) => (resolveSecond = resolve)));

    render(<EventsPage />);
    await waitFor(() => expect(getEvents).toHaveBeenCalledTimes(1));

    // A second request (here via the visibility handler) supersedes the first.
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(getEvents).toHaveBeenCalledTimes(2));

    // The superseded response must not end the loading state or show an empty list.
    await act(async () => {
      resolveFirst({ data: multipleEvents });
    });
    expect(screen.getByText(/loading events/i)).toBeInTheDocument();
    expect(screen.queryByText(/no events recorded yet/i)).not.toBeInTheDocument();

    await act(async () => {
      resolveSecond({ data: sampleEvents });
    });
    expect(
      await screen.findByRole("heading", { name: "web-app" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/loading events/i)).not.toBeInTheDocument();
  });
});
