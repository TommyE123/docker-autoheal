import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ValidationModal from "./ValidationModal";

const config = {
  monitor: { interval_seconds: 30 },
  restart: {
    cooldown_seconds: 10,
    max_restarts: 3,
    max_restarts_window_seconds: 60,
  },
};

describe("ValidationModal", () => {
  it("lists every validation error and suggestion passed in", () => {
    render(
      <ValidationModal
        show
        title="Invalid Configuration"
        message="Something is wrong"
        errors={["Window too small", "Interval too short"]}
        suggestions={["Increase the window"]}
        config={config}
        onHide={vi.fn()}
      />,
    );

    expect(screen.getByText("Window too small")).toBeInTheDocument();
    expect(screen.getByText("Interval too short")).toBeInTheDocument();
    expect(screen.getByText("Increase the window")).toBeInTheDocument();
  });

  it("calls onHide when the close button is clicked", async () => {
    const user = userEvent.setup();
    const onHide = vi.fn();

    render(
      <ValidationModal
        show
        title="Invalid Configuration"
        message="Something is wrong"
        errors={[]}
        suggestions={[]}
        config={config}
        onHide={onHide}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /close and adjust settings/i }),
    );

    expect(onHide).toHaveBeenCalledTimes(1);
  });
});
