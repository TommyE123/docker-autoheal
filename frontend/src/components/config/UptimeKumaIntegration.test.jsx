import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

  const baseProps = () => ({
    config: { enabled: false, server_url: "http://kuma.local", api_token: "tok" },
    monitors: [],
    containers: [],
    mappings: [],
    onConfigChange: vi.fn(),
    onTestConnection: vi.fn(),
    onEnableIntegration: vi.fn(),
    onDisableIntegration: vi.fn(),
    onAddMapping: vi.fn(),
    onDeleteMapping: vi.fn(),
    onShowDisableModal: vi.fn(),
  });

  describe("disabled state", () => {
    it("renders without a config and hides the disable button", () => {
      render(<UptimeKumaIntegration {...baseProps()} config={undefined} />);

      expect(screen.getByText("Disabled")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /disable integration/i }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /test connection/i })).toBeDisabled();
    });

    it("forwards edits in the connection form to onConfigChange", async () => {
      const user = userEvent.setup();
      const props = baseProps();
      render(<UptimeKumaIntegration {...props} config={{ enabled: false }} />);

      await user.type(screen.getByPlaceholderText("http://localhost:3001"), "h");

      expect(props.onConfigChange).toHaveBeenCalledWith({ enabled: false, server_url: "h" });
    });

    it("shows a Testing state while the connection test is pending", async () => {
      const user = userEvent.setup();
      let resolveTest;
      const props = baseProps();
      props.onTestConnection.mockReturnValue(new Promise((r) => (resolveTest = r)));
      render(<UptimeKumaIntegration {...props} />);

      await user.click(screen.getByRole("button", { name: /test connection/i }));

      expect(await screen.findByText(/testing\.\.\./i)).toBeInTheDocument();
      expect(props.onTestConnection).toHaveBeenCalledTimes(1);

      resolveTest(false);
      expect(
        await screen.findByRole("button", { name: /test connection/i }),
      ).toBeInTheDocument();
    });

    it("keeps offering Test Connection when the test fails", async () => {
      const user = userEvent.setup();
      const props = baseProps();
      props.onTestConnection.mockResolvedValue(false);
      render(<UptimeKumaIntegration {...props} />);

      await user.click(screen.getByRole("button", { name: /test connection/i }));

      await waitFor(() => expect(props.onTestConnection).toHaveBeenCalled());
      expect(screen.getByRole("button", { name: /test connection/i })).toBeEnabled();
      expect(
        screen.queryByRole("button", { name: /enable integration/i }),
      ).not.toBeInTheDocument();
    });

    it("offers Enable Integration after a successful test and can retest", async () => {
      const user = userEvent.setup();
      const props = baseProps();
      props.onTestConnection.mockResolvedValue(true);
      render(<UptimeKumaIntegration {...props} />);

      await user.click(screen.getByRole("button", { name: /test connection/i }));

      expect(
        await screen.findByRole("button", { name: /enable integration/i }),
      ).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /test again/i }));
      expect(props.onTestConnection).toHaveBeenCalledTimes(2);
    });

    it("shows an Enabling state until onEnableIntegration resolves", async () => {
      const user = userEvent.setup();
      let resolveEnable;
      const props = baseProps();
      props.onTestConnection.mockResolvedValue(true);
      props.onEnableIntegration.mockReturnValue(new Promise((r) => (resolveEnable = r)));
      render(<UptimeKumaIntegration {...props} />);

      await user.click(screen.getByRole("button", { name: /test connection/i }));
      await user.click(await screen.findByRole("button", { name: /enable integration/i }));

      expect(await screen.findByText(/enabling\.\.\./i)).toBeInTheDocument();
      expect(props.onEnableIntegration).toHaveBeenCalledTimes(1);

      resolveEnable();
      expect(
        await screen.findByRole("button", { name: /enable integration/i }),
      ).toBeEnabled();
    });
  });

  describe("enabled state", () => {
    const enabledProps = () => ({
      ...baseProps(),
      config: { enabled: true, server_url: "http://kuma.local" },
      monitors: [
        { friendly_name: "web-monitor", status: 1 },
        { friendly_name: "db-monitor", status: 0 },
      ],
      containers: [{ id: "abc123", name: "web-app", status: "running" }],
      mappings: [
        { container_id: "abc123", monitor_friendly_name: "web-monitor", auto_mapped: false },
      ],
    });

    it("summarises the monitor and mapping counts", () => {
      render(<UptimeKumaIntegration {...enabledProps()} />);

      const summary = screen.getByText("Monitors:").parentElement;
      expect(summary).toHaveTextContent("Monitors: 2 | Mappings: 1");
    });

    it("hides the connection form and shows the mappings section", () => {
      render(<UptimeKumaIntegration {...enabledProps()} />);

      expect(
        screen.queryByRole("button", { name: /test connection/i }),
      ).not.toBeInTheDocument();
      expect(screen.getByText("Container-Monitor Mappings")).toBeInTheDocument();
    });

    it("shows the monitors list only when monitors exist", () => {
      const { unmount } = render(<UptimeKumaIntegration {...enabledProps()} />);
      expect(screen.getByText("Available Uptime-Kuma Monitors")).toBeInTheDocument();
      unmount();

      render(<UptimeKumaIntegration {...enabledProps()} monitors={[]} />);
      expect(screen.queryByText("Available Uptime-Kuma Monitors")).not.toBeInTheDocument();
      expect(screen.getByText("Container-Monitor Mappings")).toBeInTheDocument();
    });
  });
});

