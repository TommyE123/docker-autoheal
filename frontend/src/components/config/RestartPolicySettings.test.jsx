import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RestartPolicySettings from "./RestartPolicySettings";

const config = {
  mode: "on-failure",
  cooldown_seconds: 10,
  max_restarts: 3,
  max_restarts_window_seconds: 300,
  respect_manual_stop: true,
};

describe("RestartPolicySettings", () => {
  it("reports a changed restart mode to onConfigChange", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(
      <RestartPolicySettings
        config={config}
        onConfigChange={onConfigChange}
        onSubmit={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Restart Mode"), "both");

    expect(onConfigChange).toHaveBeenCalledWith({ ...config, mode: "both" });
  });

  it("toggles respect_manual_stop when the checkbox is clicked", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(
      <RestartPolicySettings
        config={config}
        onConfigChange={onConfigChange}
        onSubmit={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText("Respect Manual Stop"));

    expect(screen.getByLabelText("Cooldown (seconds)")).toBeInTheDocument();
    expect(screen.getByLabelText("Max Restarts")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Max Restarts Window (seconds)"),
    ).toBeInTheDocument();

    expect(onConfigChange).toHaveBeenCalledWith({
      ...config,
      respect_manual_stop: false,
    });
  });

  it.each([
    ["Cooldown (seconds)", "cooldown_seconds", "20"],
    ["Max Restarts", "max_restarts", "5"],
    ["Max Restarts Window (seconds)", "max_restarts_window_seconds", "900"],
  ])("reports a changed %s as a number", (label, field, value) => {
    const onConfigChange = vi.fn();

    render(
      <RestartPolicySettings
        config={config}
        onConfigChange={onConfigChange}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText(label), { target: { value } });

    expect(onConfigChange).toHaveBeenCalledWith({
      ...config,
      [field]: Number(value),
    });
  });
});
