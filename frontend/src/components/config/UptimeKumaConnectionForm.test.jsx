import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UptimeKumaConnectionForm from "./UptimeKumaConnectionForm";

describe("UptimeKumaConnectionForm", () => {
  it("disables Test Connection until both server URL and API key are filled in", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    const { rerender } = render(
      <UptimeKumaConnectionForm
        config={{}}
        onConfigChange={onConfigChange}
        onTestConnection={vi.fn()}
        onEnableIntegration={vi.fn()}
        testingConnection={false}
        connectionTested={false}
        enablingIntegration={false}
      />,
    );

    const testButton = screen.getByRole("button", { name: /test connection/i });
    expect(testButton).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText("http://localhost:3001"),
      "http://kuma.local",
    );
    expect(onConfigChange).toHaveBeenCalled();

    rerender(
      <UptimeKumaConnectionForm
        config={{ server_url: "http://kuma.local", api_token: "token123" }}
        onConfigChange={onConfigChange}
        onTestConnection={vi.fn()}
        onEnableIntegration={vi.fn()}
        testingConnection={false}
        connectionTested={false}
        enablingIntegration={false}
      />,
    );

    expect(
      screen.getByRole("button", { name: /test connection/i }),
    ).toBeEnabled();
  });

  it("shows the Enable Integration button once the connection has been tested", () => {
    render(
      <UptimeKumaConnectionForm
        config={{ server_url: "http://kuma.local", api_token: "token123" }}
        onConfigChange={vi.fn()}
        onTestConnection={vi.fn()}
        onEnableIntegration={vi.fn()}
        testingConnection={false}
        connectionTested
        enablingIntegration={false}
      />,
    );

    expect(
      screen.getByRole("button", { name: /enable integration/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^test connection$/i }),
    ).not.toBeInTheDocument();
  });
});
