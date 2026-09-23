import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ObservabilitySettings from "./ObservabilitySettings";

const config = { log_level: "INFO", prometheus_enabled: false };

describe("ObservabilitySettings", () => {
  it("reports a changed log level to onConfigChange", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(
      <ObservabilitySettings
        config={config}
        onConfigChange={onConfigChange}
        onSubmit={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByRole("combobox"), "DEBUG");

    expect(onConfigChange).toHaveBeenCalledWith({
      ...config,
      log_level: "DEBUG",
    });
  });

  it("enables Prometheus metrics when the checkbox is checked", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(
      <ObservabilitySettings
        config={config}
        onConfigChange={onConfigChange}
        onSubmit={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("checkbox"));

    expect(onConfigChange).toHaveBeenCalledWith({
      ...config,
      prometheus_enabled: true,
    });
  });
});
