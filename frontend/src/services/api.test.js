import { describe, it, expect, vi, beforeEach } from "vitest";

const mockInstance = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    create: vi.fn(() => mockInstance),
    get: vi.fn(),
  },
}));

import axios from "axios";
import * as api from "./api";

// api.js calls axios.create() once at import time. Vitest 5 clears mock call
// history before each test (clearMocks defaults to true), so capture the
// config here rather than asserting on axios.create inside the test.
const createConfig = axios.create.mock.calls[0]?.[0];

beforeEach(() => {
  mockInstance.get.mockClear();
  mockInstance.post.mockClear();
  mockInstance.put.mockClear();
  mockInstance.delete.mockClear();
  axios.get.mockClear();
});

describe("api service", () => {
  it("creates the axios instance with a JSON content type and no-cache headers", () => {
    expect(createConfig).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "Cache-Control": "no-cache, no-store, must-revalidate",
        }),
      }),
    );
  });

  it("requests events with only the limit by default", () => {
    api.getEvents();
    expect(mockInstance.get).toHaveBeenCalledWith("/events", {
      params: { limit: 50 },
    });
  });

  it("passes event_type and container, omitting empty values", () => {
    api.getEvents(25, { eventType: "restart", container: "web" });
    expect(mockInstance.get).toHaveBeenCalledWith("/events", {
      params: { limit: 25, event_type: "restart", container: "web" },
    });

    api.getEvents(100, { eventType: "", container: "" });
    expect(mockInstance.get).toHaveBeenLastCalledWith("/events", {
      params: { limit: 100 },
    });
  });

  it("requests containers including stopped ones when asked", () => {
    api.getContainers(true);
    expect(mockInstance.get).toHaveBeenCalledWith("/containers", {
      params: { include_stopped: true },
    });
  });

  it("defaults to excluding stopped containers", () => {
    api.getContainers();
    expect(mockInstance.get).toHaveBeenCalledWith("/containers", {
      params: { include_stopped: false },
    });
  });

  it("calls the health endpoint directly via axios, bypassing the API instance", () => {
    api.getHealth();
    expect(axios.get).toHaveBeenCalledWith("/health");
    expect(mockInstance.get).not.toHaveBeenCalled();
  });

  it("posts container selection updates with the container ids and enabled flag", () => {
    api.updateContainerSelection(["abc123", "def456"], true);
    expect(mockInstance.post).toHaveBeenCalledWith("/containers/select", {
      container_ids: ["abc123", "def456"],
      enabled: true,
    });
  });

  it("builds multipart form data when importing a config file", () => {
    const file = new File(["{}"], "config.json", { type: "application/json" });
    api.importConfig(file);

    expect(mockInstance.post).toHaveBeenCalledWith(
      "/config/import",
      expect.any(FormData),
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    const formData = mockInstance.post.mock.calls[0][1];
    expect(formData.get("file")).toBe(file);
  });

  it("deletes a notification service by name", () => {
    api.deleteNotificationService("discord-alerts");
    expect(mockInstance.delete).toHaveBeenCalledWith(
      "/notifications/services/discord-alerts",
    );
  });

  it("tests an unsaved notification service by posting its values", () => {
    const service = { name: "Draft", type: "webhook", url: "https://x.test" };
    api.testUnsavedNotificationService(service);
    expect(mockInstance.post).toHaveBeenCalledWith(
      "/notifications/test",
      service,
    );
  });
});

describe("api error handling", () => {
  it.each([
    [
      "network error",
      Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" }),
    ],
    [
      "HTTP 500",
      Object.assign(new Error("Request failed with status code 500"), {
        response: { status: 500 },
      }),
    ],
    [
      "timeout",
      Object.assign(new Error("timeout of 10000ms exceeded"), {
        code: "ECONNABORTED",
      }),
    ],
  ])("propagates a %s to the caller unchanged", async (_label, error) => {
    mockInstance.get.mockRejectedValueOnce(error);
    await expect(api.getSystemStatus()).rejects.toBe(error);
  });

  it("propagates a failed health check from the bare axios call", async () => {
    const error = Object.assign(new Error("Network Error"), {
      code: "ERR_NETWORK",
    });
    axios.get.mockRejectedValueOnce(error);
    await expect(api.getHealth()).rejects.toBe(error);
  });
});

describe("api endpoint wrappers", () => {
  const config = { interval_seconds: 30 };

  it.each([
    ["getSystemStatus", () => api.getSystemStatus(), "get", ["/status"]],
    [
      "getContainerDetails",
      () => api.getContainerDetails("abc"),
      "get",
      ["/containers/abc"],
    ],
    [
      "restartContainer",
      () => api.restartContainer("abc"),
      "post",
      ["/containers/abc/restart"],
    ],
    [
      "unquarantineContainer",
      () => api.unquarantineContainer("abc"),
      "post",
      ["/containers/abc/unquarantine"],
    ],
    ["getConfig", () => api.getConfig(), "get", ["/config"]],
    [
      "updateConfig",
      () => api.updateConfig(config),
      "put",
      ["/config", config],
    ],
    [
      "updateMonitorConfig",
      () => api.updateMonitorConfig(config),
      "put",
      ["/config/monitor", config],
    ],
    [
      "updateRestartConfig",
      () => api.updateRestartConfig(config),
      "put",
      ["/config/restart", config],
    ],
    ["exportConfig", () => api.exportConfig(), "get", ["/config/export"]],
    [
      "updateObservabilityConfig",
      () => api.updateObservabilityConfig(config),
      "put",
      ["/config/observability", config],
    ],
    ["getHealthChecks", () => api.getHealthChecks(), "get", ["/healthchecks"]],
    [
      "getHealthCheck",
      () => api.getHealthCheck("abc"),
      "get",
      ["/healthchecks/abc"],
    ],
    [
      "addHealthCheck",
      () => api.addHealthCheck(config),
      "post",
      ["/healthchecks", config],
    ],
    [
      "deleteHealthCheck",
      () => api.deleteHealthCheck("abc"),
      "delete",
      ["/healthchecks/abc"],
    ],
    ["clearEvents", () => api.clearEvents(), "delete", ["/events"]],
    [
      "enableMaintenanceMode",
      () => api.enableMaintenanceMode(),
      "post",
      ["/maintenance/enable"],
    ],
    [
      "disableMaintenanceMode",
      () => api.disableMaintenanceMode(),
      "post",
      ["/maintenance/disable"],
    ],
    [
      "getMaintenanceStatus",
      () => api.getMaintenanceStatus(),
      "get",
      ["/maintenance/status"],
    ],
    [
      "getNotificationsConfig",
      () => api.getNotificationsConfig(),
      "get",
      ["/notifications/config"],
    ],
    [
      "updateNotificationsConfig",
      () => api.updateNotificationsConfig(config),
      "put",
      ["/notifications/config", config],
    ],
    [
      "addNotificationService",
      () => api.addNotificationService(config),
      "post",
      ["/notifications/services", config],
    ],
    [
      "updateNotificationService",
      () => api.updateNotificationService("discord", config),
      "put",
      ["/notifications/services/discord", config],
    ],
    [
      "testNotificationService",
      () => api.testNotificationService("discord"),
      "post",
      ["/notifications/test/discord"],
    ],
    [
      "getContainers",
      () => api.getContainers(true),
      "get",
      ["/containers", { params: { include_stopped: true } }],
    ],
    [
      "updateContainerSelection",
      () => api.updateContainerSelection(["abc"], true),
      "post",
      ["/containers/select", { container_ids: ["abc"], enabled: true }],
    ],
    [
      "getEvents",
      () => api.getEvents(10, { eventType: "restart" }),
      "get",
      ["/events", { params: { limit: 10, event_type: "restart" } }],
    ],
    [
      "deleteNotificationService",
      () => api.deleteNotificationService("discord"),
      "delete",
      ["/notifications/services/discord"],
    ],
    [
      "testUnsavedNotificationService",
      () => api.testUnsavedNotificationService(config),
      "post",
      ["/notifications/test", config],
    ],
  ])("%s calls the expected endpoint", (_name, call, method, expectedArgs) => {
    call();
    expect(mockInstance[method]).toHaveBeenCalledWith(...expectedArgs);
  });
});
