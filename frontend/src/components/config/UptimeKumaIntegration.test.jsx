import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UptimeKumaIntegration from "./UptimeKumaIntegration";

describe("UptimeKumaIntegration", () => {
  it("shows the connection form when integration is disabled", () => {
    render(
      <UptimeKumaIntegration
        config={{ enabled: false }}
        monitors={[]}
        containers={[]}
        mappings={[]}
        onConfigChange={vi.fn()}
        onTestConnection={vi.fn()}
        onEnableIntegration={vi.fn()}
        onDisableIntegration={vi.fn()}
        onAddMapping={vi.fn()}
        onDeleteMapping={vi.fn()}
        onShowDisableModal={vi.fn()}
      />,
    );

    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /test connection/i }),
    ).toBeInTheDocument();
  });

  it("shows connection details and a disable button when integration is enabled", async () => {
    const user = userEvent.setup();
    const onShowDisableModal = vi.fn();

    render(
      <UptimeKumaIntegration
        config={{ enabled: true, server_url: "http://kuma.local" }}
        monitors={[{ friendly_name: "web-monitor", status: 1 }]}
        containers={[]}
        mappings={[]}
        onConfigChange={vi.fn()}
        onTestConnection={vi.fn()}
        onEnableIntegration={vi.fn()}
        onDisableIntegration={vi.fn()}
        onAddMapping={vi.fn()}
        onDeleteMapping={vi.fn()}
        onShowDisableModal={onShowDisableModal}
      />,
    );

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/http:\/\/kuma\.local/)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /disable integration/i }),
    );
    expect(onShowDisableModal).toHaveBeenCalledTimes(1);
  });
});
