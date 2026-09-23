import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MonitorSettings from "./MonitorSettings";

const config = {
  interval_seconds: 30,
  label_key: "autoheal",
  label_value: "true",
  include_all: false,
};

function ControlledMonitorSettings({ onConfigChange, onSubmit }) {
  const [current, setCurrent] = useState(config);
  return (
    <MonitorSettings
      config={current}
      onConfigChange={(next) => {
        setCurrent(next);
        onConfigChange(next);
      }}
      onSubmit={onSubmit}
    />
  );
}

describe("MonitorSettings", () => {
  it("reports an updated interval to onConfigChange", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(
      <ControlledMonitorSettings
        onConfigChange={onConfigChange}
        onSubmit={vi.fn()}
      />,
    );

    const intervalInput = screen.getByRole("spinbutton");
    await user.clear(intervalInput);
    await user.type(intervalInput, "60");

    expect(onConfigChange).toHaveBeenLastCalledWith({
      ...config,
      interval_seconds: 60,
    });
  });

  it("calls onSubmit when the form is submitted", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <MonitorSettings
        config={config}
        onConfigChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /save monitor settings/i }),
    );

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
