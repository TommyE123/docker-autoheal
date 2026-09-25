import { Component } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { format } from "date-fns";

// EventsPage has no error boundary of its own; this one exists only so the
// test can observe the render error synchronously instead of it surfacing
// as an unhandled/uncaught exception via React's default reporting.
class TestErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    if (this.props.onError) {
      this.props.onError(error);
    }
  }

  render() {
    if (this.state.error) {
      return null;
    }
    return this.props.children;
  }
}

vi.mock("../services/api", () => ({
  getEvents: vi.fn(),
  clearEvents: vi.fn(),
}));

import { getEvents } from "../services/api";
import EventsPage from "./EventsPage";

const baseEvent = {
  container_id: "abc123",
  container_name: "web-app",
  event_type: "restart",
  status: "success",
  message: "Container restarted",
  restart_count: 1,
};

const pinnedTimestamps = [
  ["2024-01-01T00:00:00Z", "Jan 1, 2024, 12:00:00 AM"],
  ["2024-01-02T12:30:00Z", "Jan 2, 2024, 12:30:00 PM"],
  ["2024-01-03T08:15:00Z", "Jan 3, 2024, 8:15:00 AM"],
  ["2024-02-29T12:00:00Z", "Feb 29, 2024, 12:00:00 PM"],
  ["2024-03-09T23:59:59Z", "Mar 9, 2024, 11:59:59 PM"],
  ["2024-12-31T13:05:09Z", "Dec 31, 2024, 1:05:09 PM"],
  ["2025-07-04T00:00:01Z", "Jul 4, 2025, 12:00:01 AM"],
];

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EventsPage timestamp formatting (date-fns v4 upgrade guard)", () => {
  it("runs with the timezone pinned to UTC", () => {
    expect(new Date().getTimezoneOffset()).toBe(0);
  });

  describe.each(pinnedTimestamps)("timestamp %s", (timestamp, expected) => {
    it(`renders as "${expected}"`, async () => {
      getEvents.mockResolvedValue({
        data: [{ ...baseEvent, timestamp }],
      });

      render(<EventsPage />);

      expect(await screen.findByText(expected)).toBeInTheDocument();
    });

    it(`date-fns format(x, 'PPpp') produces "${expected}"`, () => {
      expect(format(new Date(timestamp), "PPpp")).toBe(expected);
    });
  });

  describe("invalid timestamps (current behaviour, not a desired contract)", () => {
    it.each([
      ["undefined", undefined],
      ["a non-date string", "not-a-date"],
    ])(
      "throws a RangeError when timestamp is %s",
      async (_label, timestamp) => {
        vi.spyOn(console, "error").mockImplementation(() => {});
        getEvents.mockResolvedValue({
          data: [{ ...baseEvent, timestamp }],
        });

        const onError = vi.fn();
        render(
          <TestErrorBoundary onError={onError}>
            <EventsPage />
          </TestErrorBoundary>,
        );
        await waitFor(() => expect(onError).toHaveBeenCalled());

        const caughtError = onError.mock.calls[0][0];
        expect(caughtError).toBeInstanceOf(RangeError);
        expect(caughtError.message).toBe("Invalid time value");
      },
    );

    it('renders "Jan 1, 1970, 12:00:00 AM" when timestamp is null', async () => {
      getEvents.mockResolvedValue({
        data: [{ ...baseEvent, timestamp: null }],
      });

      render(<EventsPage />);

      expect(
        await screen.findByText("Jan 1, 1970, 12:00:00 AM"),
      ).toBeInTheDocument();
    });
  });
});
