import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within, act } from "@testing-library/react";
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

  it("clears the pending alert timer when unmounted", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    updateNotificationsConfig.mockResolvedValue({});

    const { unmount } = render(<NotificationsPage />);
    await screen.findByText(/notifications are disabled/i);
    await user.click(screen.getByRole("checkbox"));
    await screen.findByText(/notifications enabled/i);

    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    unmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();
    clearTimeoutSpy.mockRestore();
  });

  it("shows a message when no notification services are configured", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    expect(
      await screen.findByText(/no notification services configured/i),
    ).toBeInTheDocument();
  });

  it("quotes the Add Service button name in the empty-state message", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    expect(
      await screen.findByText(
        'No notification services configured. Click "Add Service" to get started.',
      ),
    ).toBeInTheDocument();
  });

  it("loads the configuration exactly once on mount", async () => {
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);
    await screen.findByText(/notifications are disabled/i);
    await act(async () => {});

    expect(getNotificationsConfig).toHaveBeenCalledTimes(1);
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

    const botTokenInput = screen.getByPlaceholderText(/123456789:abcdefghijklmnopqrstuvwxyz/i);
    await user.type(botTokenInput, "   ");
    expect(addButton).toBeDisabled();

    await user.clear(botTokenInput);
    await user.type(botTokenInput, "123:abc");
    expect(addButton).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/-1001234567890/i), "456");
    expect(addButton).toBeEnabled();
  });

  // Guards against a new entry in the service type dropdown being added without a
  // matching REQUIRED_FIELDS_BY_TYPE entry, which would silently fall back to
  // validating the name only.
  it("keeps the add button disabled for every service type when only the name is filled in", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);

    await user.click(screen.getByRole("button", { name: /add service/i }));
    await user.type(screen.getByPlaceholderText(/my discord server/i), "Name Only");

    const typeSelect = screen.getByRole("combobox");
    const serviceTypes = Array.from(typeSelect.options, (option) => option.value);
    expect(serviceTypes.length).toBeGreaterThan(0);

    const addButton = screen.getByRole("button", { name: /^add service$/i });
    for (const serviceType of serviceTypes) {
      await user.selectOptions(typeSelect, serviceType);
      expect(
        addButton,
        `service type "${serviceType}" has no required-field validation`,
      ).toBeDisabled();
    }
  });

  it("keeps the update button disabled for an existing service whose required field is null", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({
      data: {
        ...configWithServices,
        services: [{ name: "Legacy Webhook", type: "webhook", enabled: true, url: null }],
      },
    });

    render(<NotificationsPage />);

    await screen.findByText("Legacy Webhook");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    const updateButton = screen.getByRole("button", { name: /update service/i });
    expect(updateButton).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText(/https:\/\/example\.com\/webhook/i),
      "https://example.com/hook",
    );

    expect(updateButton).toBeEnabled();
  });

  it("falls back to name-only validation for a service of an unrecognised type", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({
      data: {
        ...configWithServices,
        services: [{ name: "Future Service", type: "carrier-pigeon", enabled: true }],
      },
    });

    render(<NotificationsPage />);

    await screen.findByText("Future Service");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    expect(screen.getByRole("button", { name: /update service/i })).toBeEnabled();
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

  it("shows an alert and leaves the state unchanged when toggling notifications fails", async () => {
    const user = userEvent.setup();
    getNotificationsConfig.mockResolvedValue({ data: config });
    updateNotificationsConfig.mockRejectedValue(new Error("nope"));

    render(<NotificationsPage />);

    await screen.findByText(/notifications are disabled/i);
    await user.click(screen.getByRole("checkbox"));

    expect(await screen.findByText(/failed to update notifications/i)).toBeInTheDocument();
    expect(screen.getByText(/notifications are disabled/i)).toBeInTheDocument();
  });

  describe("event filters", () => {
    it("explains that all events notify when no filter is selected", async () => {
      getNotificationsConfig.mockResolvedValue({ data: config });

      render(<NotificationsPage />);

      expect(
        await screen.findByText(/no filters selected - all events will trigger notifications/i),
      ).toBeInTheDocument();
    });

    it("adds an event type to the filters when its badge is clicked", async () => {
      const user = userEvent.setup();
      getNotificationsConfig.mockResolvedValue({ data: { ...config, event_filters: ["restart"] } });
      updateNotificationsConfig.mockResolvedValue({});

      render(<NotificationsPage />);

      await user.click(await screen.findByText("Container Quarantine"));

      await waitFor(() =>
        expect(updateNotificationsConfig).toHaveBeenCalledWith({
          event_filters: ["restart", "quarantine"],
        }),
      );
      expect(await screen.findByText(/event filters updated/i)).toBeInTheDocument();
      expect(screen.getByText(/container quarantine ✓/i)).toBeInTheDocument();
      expect(
        screen.queryByText(/no filters selected/i),
      ).not.toBeInTheDocument();
    });

    it("removes an already selected event type from the filters", async () => {
      const user = userEvent.setup();
      getNotificationsConfig.mockResolvedValue({
        data: { ...config, event_filters: ["restart", "quarantine"] },
      });
      updateNotificationsConfig.mockResolvedValue({});

      render(<NotificationsPage />);

      await user.click(await screen.findByText(/container restart/i));

      await waitFor(() =>
        expect(updateNotificationsConfig).toHaveBeenCalledWith({ event_filters: ["quarantine"] }),
      );
    });

    it("shows an alert and keeps the previous filters when updating fails", async () => {
      const user = userEvent.setup();
      getNotificationsConfig.mockResolvedValue({ data: config });
      updateNotificationsConfig.mockRejectedValue(new Error("nope"));

      render(<NotificationsPage />);

      await user.click(await screen.findByText("Auto Monitor"));

      expect(await screen.findByText(/failed to update event filters/i)).toBeInTheDocument();
      expect(screen.queryByText(/auto monitor ✓/i)).not.toBeInTheDocument();
    });
  });

  describe("type-specific service payloads", () => {
    async function openAddModal(type, name) {
      const user = userEvent.setup();
      getNotificationsConfig.mockResolvedValue({ data: config });
      addNotificationService.mockResolvedValue({});

      render(<NotificationsPage />);
      await screen.findByText(/notifications are disabled/i);

      await user.click(screen.getByRole("button", { name: /add service/i }));
      await user.type(screen.getByPlaceholderText(/my discord server/i), name);
      await user.selectOptions(screen.getByRole("combobox"), type);
      return user;
    }

    async function submitAndGetPayload(user) {
      await user.click(screen.getByRole("button", { name: /^add service$/i }));
      await waitFor(() => expect(addNotificationService).toHaveBeenCalledTimes(1));
      return addNotificationService.mock.calls[0][0];
    }

    it("sends the url and optional username for a discord service", async () => {
      const user = await openAddModal("discord", "Discord");
      await user.type(
        screen.getByPlaceholderText(/discord\.com\/api\/webhooks/i),
        "https://discord.com/api/webhooks/1",
      );
      await user.type(screen.getByPlaceholderText("Docker Auto-Heal"), "autoheal-bot");

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Discord",
        type: "discord",
        enabled: true,
        url: "https://discord.com/api/webhooks/1",
        username: "autoheal-bot",
      });
    });

    it("sends only the url for a slack service", async () => {
      const user = await openAddModal("slack", "Slack");
      await user.type(
        screen.getByPlaceholderText(/hooks\.slack\.com/i),
        "https://hooks.slack.com/services/x",
      );

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Slack",
        type: "slack",
        enabled: true,
        url: "https://hooks.slack.com/services/x",
      });
    });

    it("sends the bot token and chat id for a telegram service", async () => {
      const user = await openAddModal("telegram", "Telegram");
      await user.type(screen.getByPlaceholderText(/123456789:abc/i), "123:abc");
      await user.type(screen.getByPlaceholderText("-1001234567890"), "456");

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Telegram",
        type: "telegram",
        enabled: true,
        bot_token: "123:abc",
        chat_id: "456",
      });
    });

    it("sends the topic and optional credentials for an ntfy service", async () => {
      const user = await openAddModal("ntfy", "Ntfy");
      await user.type(screen.getByPlaceholderText("docker-autoheal"), "alerts");
      await user.type(screen.getByPlaceholderText(/ntfy\.sh/i), "https://ntfy.example.com");
      const [username] = screen.getAllByRole("textbox").slice(-1);
      await user.type(username, "me");
      await user.type(document.querySelector('input[type="password"]'), "secret");

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Ntfy",
        type: "ntfy",
        enabled: true,
        topic: "alerts",
        server_url: "https://ntfy.example.com",
        username: "me",
        password: "secret",
      });
    });

    it("sends the access token for an ntfy service", async () => {
      const user = await openAddModal("ntfy", "Ntfy");
      await user.type(screen.getByPlaceholderText("docker-autoheal"), "alerts");
      await user.type(screen.getByPlaceholderText("tk_..."), "tk_secret");

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Ntfy",
        type: "ntfy",
        enabled: true,
        topic: "alerts",
        access_token: "tk_secret",
      });
    });

    it("sends the server url and app token for a gotify service", async () => {
      const user = await openAddModal("gotify", "Gotify");
      await user.type(
        screen.getByPlaceholderText("https://gotify.example.com"),
        "https://gotify.local",
      );
      await user.type(screen.getByPlaceholderText("AaBbCcDdEeFf"), "apptok");

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Gotify",
        type: "gotify",
        enabled: true,
        server_url: "https://gotify.local",
        app_token: "apptok",
      });
    });

    it("sends the user key and api token for a pushover service", async () => {
      const user = await openAddModal("pushover", "Pushover");
      await user.type(screen.getByPlaceholderText("uQiRzpo4DXghDmr9QzzfQu27cmVRsG"), "ukey");
      await user.type(screen.getByPlaceholderText("azGDORePK8gMaC0QOYAMyEEuzJnyUi"), "atok");

      expect(await submitAndGetPayload(user)).toEqual({
        name: "Pushover",
        type: "pushover",
        enabled: true,
        user_key: "ukey",
        api_token: "atok",
      });
    });
  });
});

