import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../services/api", () => ({
  getNotificationsConfig: vi.fn(),
  updateNotificationsConfig: vi.fn(),
  addNotificationService: vi.fn(),
  updateNotificationService: vi.fn(),
  deleteNotificationService: vi.fn(),
  testNotificationService: vi.fn(),
}));

import {
  getNotificationsConfig,
  updateNotificationsConfig,
  addNotificationService,
  updateNotificationService,
  deleteNotificationService,
  testNotificationService,
} from "../services/api";
import NotificationsPage from "./NotificationsPage";

const config = {
  enabled: false,
  event_filters: [],
  services: [],
};

const configWithServices = {
  enabled: true,
  event_filters: [],
  services: [
    { name: "My Webhook", type: "webhook", enabled: true, url: "https://example.com/webhook" },
    { name: "Disabled Slack", type: "slack", enabled: false, url: "https://hooks.slack.com/services/x" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NotificationsPage", () => {
  it("shows the current enabled/disabled state after loading", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    expect(
      await screen.findByText(/notifications are disabled/i),
    ).toBeInTheDocument();
  });

  it("toggles notifications on when the switch is clicked", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    updateNotificationsConfig.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("checkbox"));

    await waitFor(() =>
      expect(updateNotificationsConfig).toHaveBeenCalledWith({ enabled: true }),
    );
  });

  it("shows a message when no notification services are configured", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    expect(
      await screen.findByText(/no notification services configured/i),
    ).toBeInTheDocument();
  });

  it("shows an alert when loading the configuration fails", async () => {
    getNotificationsConfig.mockRejectedValue(new Error("network error"));

    render(<NotificationsPage />);

    expect(
      await screen.findByText(/failed to load notifications configuration/i),
    ).toBeInTheDocument();
  });

  it("lists configured services with their type and status", async () => {
    getNotificationsConfig.mockResolvedValue({ data: configWithServices });

    render(<NotificationsPage />);

    expect(await screen.findByText("My Webhook")).toBeInTheDocument();
    expect(screen.getByText("Disabled Slack")).toBeInTheDocument();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Enabled")).toBeInTheDocument();
    expect(within(table).getByText("Disabled")).toBeInTheDocument();
  });

  it("adds a new service successfully", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    addNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("button", { name: /add service/i }));

    await user.type(screen.getByPlaceholderText(/my discord server/i), "New Webhook");
    await user.type(
      screen.getByPlaceholderText(/https:\/\/example\.com\/webhook/i),
      "https://example.com/hook",
    );

    getNotificationsConfig.mockResolvedValue({
      data: { ...config, services: [{ name: "New Webhook", type: "webhook", enabled: true }] },
    });

    await user.click(screen.getByRole("button", { name: /^add service$/i }));

    await waitFor(() =>
      expect(addNotificationService).toHaveBeenCalledWith(
        expect.objectContaining({ name: "New Webhook", type: "webhook", url: "https://example.com/hook" }),
      ),
    );
    expect(
      await screen.findByText(/notification service added successfully/i),
    ).toBeInTheDocument();
    expect(await screen.findByText("New Webhook")).toBeInTheDocument();
  });

  it("disables the add button while required fields are missing", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("button", { name: /add service/i }));

    expect(screen.getByRole("button", { name: /^add service$/i })).toBeDisabled();
  });

  it("shows an alert when adding a service fails", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    addNotificationService.mockRejectedValue({
      response: { data: { detail: "Service already exists" } },
    });

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("button", { name: /add service/i }));

    await user.type(screen.getByPlaceholderText(/my discord server/i), "New Webhook");
    await user.type(
      screen.getByPlaceholderText(/https:\/\/example\.com\/webhook/i),
      "https://example.com/hook",
    );

    await user.click(screen.getByRole("button", { name: /^add service$/i }));

    await waitFor(() =>
      expect(addNotificationService).toHaveBeenCalledWith(
        expect.objectContaining({ name: "New Webhook", type: "webhook", url: "https://example.com/hook" }),
      ),
    );
    expect(
      await screen.findByText(/service already exists/i),
    ).toBeInTheDocument();
  });

  // Issue #264 fix: the Add/Update button is now also gated on the selected
  // service type's own required field(s), not just the name.
  it("keeps the add button disabled until the type-specific required field is filled in", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    addNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("button", { name: /add service/i }));

    await user.type(screen.getByPlaceholderText(/my discord server/i), "Incomplete Webhook");

    const addButton = screen.getByRole("button", { name: /^add service$/i });
    // Name is filled in, but the webhook type's required URL is still empty.
    expect(addButton).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText(/https:\/\/example\.com\/webhook/i),
      "https://example.com/hook",
    );

    expect(addButton).toBeEnabled();

    await user.click(addButton);

    await waitFor(() =>
      expect(addNotificationService).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Incomplete Webhook",
          type: "webhook",
          url: "https://example.com/hook",
        }),
      ),
    );
    expect(
      await screen.findByText(/notification service added successfully/i),
    ).toBeInTheDocument();
  });

  it("keeps the add button disabled for a telegram service missing bot_token/chat_id", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("button", { name: /add service/i }));
    await user.type(screen.getByPlaceholderText(/my discord server/i), "Incomplete Telegram");
    await user.selectOptions(screen.getByRole("combobox"), "telegram");

    const addButton = screen.getByRole("button", { name: /^add service$/i });
    expect(addButton).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/123456789:abcdefghijklmnopqrstuvwxyz/i), "123:abc");
    expect(addButton).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/-1001234567890/i), "456");
    expect(addButton).toBeEnabled();
  });

  it("edits an existing service successfully", async () => {
    const user = userEvent.setup();
    const configAfterEdit = {
      ...configWithServices,
      services: configWithServices.services.map((service) =>
        service.name === "My Webhook"
          ? { ...service, url: "https://example.com/updated" }
          : service,
      ),
    };
    getNotificationsConfig
      .mockResolvedValueOnce({ data: configWithServices })
      .mockResolvedValueOnce({ data: configAfterEdit });
    updateNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^edit$/i })[0]);

    const urlInput = screen.getByDisplayValue("https://example.com/webhook");
    await user.clear(urlInput);
    await user.type(urlInput, "https://example.com/updated");

    await user.click(screen.getByRole("button", { name: /update service/i }));

    await waitFor(() =>
      expect(updateNotificationService).toHaveBeenCalledWith(
        "My Webhook",
        expect.objectContaining({ url: "https://example.com/updated" }),
      ),
    );
    expect(
      await screen.findByText(/notification service updated successfully/i),
    ).toBeInTheDocument();

    // The service list only shows name/type/status, so reopen the edit
    // modal to prove the refetched config actually carries the new URL
    // rather than the save handler having silently no-opped.
    await user.click(screen.getAllByRole("button", { name: /^edit$/i })[0]);
    expect(
      await screen.findByDisplayValue("https://example.com/updated"),
    ).toBeInTheDocument();
  });

  it("shows an alert when updating a service fails", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: configWithServices });
    updateNotificationService.mockRejectedValue({
      response: { data: { detail: "Service update rejected" } },
    });

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^edit$/i })[0]);
    await user.click(screen.getByRole("button", { name: /update service/i }));

    expect(
      await screen.findByText(/service update rejected/i),
    ).toBeInTheDocument();
  });

  it("enables a disabled service", async () => {
    const user = userEvent.setup();
    const configAfterEnable = {
      ...configWithServices,
      services: configWithServices.services.map((service) =>
        service.name === "Disabled Slack" ? { ...service, enabled: true } : service,
      ),
    };
    getNotificationsConfig
      .mockResolvedValueOnce({ data: configWithServices })
      .mockResolvedValueOnce({ data: configAfterEnable });
    updateNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText("Disabled Slack");

    await user.click(screen.getAllByRole("button", { name: /^edit$/i })[1]);

    const modal = screen.getByRole("dialog");
    await user.click(within(modal).getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /update service/i }));

    await waitFor(() =>
      expect(updateNotificationService).toHaveBeenCalledWith(
        "Disabled Slack",
        expect.objectContaining({ enabled: true }),
      ),
    );

    const row = screen.getByText("Disabled Slack").closest("tr");
    await waitFor(() =>
      expect(within(row).getByText("Enabled")).toBeInTheDocument(),
    );
  });

  it("disables an enabled service", async () => {
    const user = userEvent.setup();
    const configAfterDisable = {
      ...configWithServices,
      services: configWithServices.services.map((service) =>
        service.name === "My Webhook" ? { ...service, enabled: false } : service,
      ),
    };
    getNotificationsConfig
      .mockResolvedValueOnce({ data: configWithServices })
      .mockResolvedValueOnce({ data: configAfterDisable });
    updateNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^edit$/i })[0]);

    const modal = screen.getByRole("dialog");
    await user.click(within(modal).getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /update service/i }));

    await waitFor(() =>
      expect(updateNotificationService).toHaveBeenCalledWith(
        "My Webhook",
        expect.objectContaining({ enabled: false }),
      ),
    );
    expect(
      await screen.findByText(/notification service updated successfully/i),
    ).toBeInTheDocument();

    const row = screen.getByText("My Webhook").closest("tr");
    await waitFor(() =>
      expect(within(row).getByText("Disabled")).toBeInTheDocument(),
    );
  });

  it("deletes a service after confirming", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const configAfterDelete = {
      ...configWithServices,
      services: configWithServices.services.filter(
        (service) => service.name !== "My Webhook",
      ),
    };
    getNotificationsConfig
      .mockResolvedValueOnce({ data: configWithServices })
      .mockResolvedValueOnce({ data: configAfterDelete });
    deleteNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^delete$/i })[0]);

    await waitFor(() =>
      expect(deleteNotificationService).toHaveBeenCalledWith("My Webhook"),
    );
    expect(
      await screen.findByText(/notification service deleted successfully/i),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.queryByText("My Webhook")).not.toBeInTheDocument(),
    );

    confirmSpy.mockRestore();
  });

  it("does not delete a service when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    getNotificationsConfig.mockResolvedValue({ data: configWithServices });

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^delete$/i })[0]);

    expect(deleteNotificationService).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  it("shows an alert when deleting a service fails", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    getNotificationsConfig.mockResolvedValue({ data: configWithServices });
    deleteNotificationService.mockRejectedValue(new Error("delete failed"));

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^delete$/i })[0]);

    expect(
      await screen.findByText(/failed to delete notification service/i),
    ).toBeInTheDocument();

    confirmSpy.mockRestore();
  });

  it("tests a notification service and shows a success alert", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: configWithServices });
    testNotificationService.mockResolvedValue({});

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^test$/i })[0]);

    await waitFor(() =>
      expect(testNotificationService).toHaveBeenCalledWith("My Webhook"),
    );
    expect(
      await screen.findByText(/test notification sent to "my webhook"/i),
    ).toBeInTheDocument();
  });

  it("shows an alert when testing a notification service fails", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: configWithServices });
    testNotificationService.mockRejectedValue({
      response: { data: { detail: "Test send failed" } },
    });

    render(<NotificationsPage />);

    await screen.findByText("My Webhook");

    await user.click(screen.getAllByRole("button", { name: /^test$/i })[0]);

    expect(await screen.findByText(/test send failed/i)).toBeInTheDocument();
  });
});
