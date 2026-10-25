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
    expect(screen.getByLabelText("API Key")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Auto-restart containers when monitors are DOWN"),
    ).toBeInTheDocument();

    await user.type(
      screen.getByLabelText("Uptime-Kuma Server URL"),
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

  const renderForm = (props = {}) =>
    render(
      <UptimeKumaConnectionForm
        config={{ server_url: "http://kuma.local", api_token: "token123" }}
        onConfigChange={vi.fn()}
        onTestConnection={vi.fn()}
        onEnableIntegration={vi.fn()}
        testingConnection={false}
        connectionTested={false}
        enablingIntegration={false}
        {...props}
      />,
    );

  it("reports API key and auto-restart changes", async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();
    renderForm({ onConfigChange });

    await user.type(screen.getByLabelText("API Key"), "!");
    expect(onConfigChange).toHaveBeenLastCalledWith({
      server_url: "http://kuma.local",
      api_token: "token123!",
    });

    await user.click(
      screen.getByLabelText("Auto-restart containers when monitors are DOWN"),
    );
    expect(onConfigChange).toHaveBeenLastCalledWith({
      server_url: "http://kuma.local",
      api_token: "token123",
      auto_restart_on_down: false,
    });
  });

  it("toggles API key visibility", async () => {
    const user = userEvent.setup();
    renderForm();

    expect(screen.getByLabelText("API Key")).toHaveAttribute(
      "type",
      "password",
    );
    await user.click(screen.getByRole("button", { name: "Show API key" }));
    expect(screen.getByLabelText("API Key")).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Hide API key" }));
    expect(screen.getByLabelText("API Key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("shows a testing state while the connection is being tested", () => {
    renderForm({ testingConnection: true });

    expect(screen.getByRole("button", { name: /testing/i })).toBeDisabled();
  });

  it("offers Enable Integration and Test Again once the connection is tested", async () => {
    const user = userEvent.setup();
    const onEnableIntegration = vi.fn();
    const onTestConnection = vi.fn();
    renderForm({
      connectionTested: true,
      onEnableIntegration,
      onTestConnection,
    });

    await user.click(
      screen.getByRole("button", { name: /enable integration/i }),
    );
    await user.click(screen.getByRole("button", { name: /test again/i }));

    expect(onEnableIntegration).toHaveBeenCalledTimes(1);
    expect(onTestConnection).toHaveBeenCalledTimes(1);
  });

  it("shows an enabling state while the integration is being enabled", () => {
    renderForm({ connectionTested: true, enablingIntegration: true });

    expect(screen.getByRole("button", { name: /enabling/i })).toBeDisabled();
  });
});
