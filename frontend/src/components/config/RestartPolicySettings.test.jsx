import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

    await user.selectOptions(screen.getByRole("combobox"), "both");

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

    await user.click(screen.getByRole("checkbox"));

    expect(onConfigChange).toHaveBeenCalledWith({
      ...config,
      respect_manual_stop: false,
    });
  });
});
