import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MaintenanceModal from "./MaintenanceModal";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("MaintenanceModal", () => {
  it("counts up the elapsed time since startTime while shown", () => {
    const startTime = new Date(Date.now() - 5000).toISOString();

    render(<MaintenanceModal show startTime={startTime} onDismiss={vi.fn()} />);

    expect(screen.getByText("00:00:05")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(screen.getByText("00:00:08")).toBeInTheDocument();
  });

  it("calls onDismiss when the exit button is clicked", async () => {
    vi.useRealTimers();
    const user = userEvent.setup();
    const onDismiss = vi.fn();

    render(
      <MaintenanceModal
        show
        startTime={new Date().toISOString()}
        onDismiss={onDismiss}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /exit maintenance mode/i }),
    );

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("renders nothing visible when show is false", () => {
    render(
      <MaintenanceModal show={false} startTime={null} onDismiss={vi.fn()} />,
    );

    expect(
      screen.queryByText("Maintenance Mode Active"),
    ).not.toBeInTheDocument();
  });
});
