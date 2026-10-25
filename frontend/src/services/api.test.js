import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockInstance = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
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
const requestInterceptor =
  mockInstance.interceptors.request.use.mock.calls[0]?.[0];
const [responseOk, responseError] =
  mockInstance.interceptors.response.use.mock.calls[0] ?? [];

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

describe("API key handling", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("sends no X-API-Key header when no key is stored", () => {
    const config = requestInterceptor({ headers: {} });

    expect(config.headers).not.toHaveProperty("X-API-Key");
  });

  it("sends the stored key as X-API-Key", () => {
    api.setApiKey("abc");

    const config = requestInterceptor({ headers: {} });

    expect(config.headers["X-API-Key"]).toBe("abc");
  });

  it("stops sending the key once cleared", () => {
    api.setApiKey("abc");
    api.clearApiKey();

    expect(api.getApiKey()).toBeNull();
    expect(requestInterceptor({ headers: {} }).headers).not.toHaveProperty(
      "X-API-Key",
    );
  });

  it("passes successful responses through untouched", () => {
    const response = { status: 200 };

    expect(responseOk(response)).toBe(response);
  });

  it("notifies the handler on a 401 and still rejects", async () => {
    const handler = vi.fn();
    const off = api.onUnauthorized(handler);
    const error = { response: { status: 401 } };

    await expect(responseError(error)).rejects.toBe(error);
    expect(handler).toHaveBeenCalledTimes(1);

    off();
    await expect(responseError(error)).rejects.toBe(error);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not notify for other errors", async () => {
    const handler = vi.fn();
    const off = api.onUnauthorized(handler);

    await expect(responseError({ response: { status: 500 } })).rejects.toEqual({
      response: { status: 500 },
    });
    await expect(responseError(new Error("network"))).rejects.toThrow();
    expect(handler).not.toHaveBeenCalled();
    off();
  });

  it("keeps a newer handler when an older one unsubscribes late", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const offFirst = api.onUnauthorized(first);
    const offSecond = api.onUnauthorized(second);

    offFirst();
    await expect(
      responseError({ response: { status: 401 } }),
    ).rejects.toBeDefined();

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    offSecond();
  });

  it("reports whether the key was persisted", () => {
    expect(api.setApiKey("abc")).toBe(true);
    expect(sessionStorage.getItem("autoheal_api_key")).toBe("abc");
  });

  describe("when sessionStorage is unavailable", () => {
    beforeEach(() => {
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("blocked");
      });
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("blocked");
      });
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new Error("blocked");
      });
    });

    afterEach(() => {
      api.clearApiKey();
      vi.restoreAllMocks();
    });

    it("keeps the key in memory and says it was not persisted", () => {
      expect(api.setApiKey("mem")).toBe(false);

      expect(api.getApiKey()).toBe("mem");
      expect(requestInterceptor({ headers: {} }).headers["X-API-Key"]).toBe(
        "mem",
      );
    });

    it("forgets the in-memory key when cleared", () => {
      api.setApiKey("mem");

      api.clearApiKey();

      expect(api.getApiKey()).toBeNull();
    });
  });

  describe("when storage rejects a change but still holds an older key", () => {
    beforeEach(() => {
      sessionStorage.setItem("autoheal_api_key", "old");
    });

    afterEach(() => {
      vi.restoreAllMocks();
      api.clearApiKey();
    });

    it("sends the replacement key, not the stale stored one", () => {
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("quota");
      });

      expect(api.setApiKey("new")).toBe(false);

      expect(api.getApiKey()).toBe("new");
      expect(requestInterceptor({ headers: {} }).headers["X-API-Key"]).toBe(
        "new",
      );
    });

    it("stops sending a key that could not be removed from storage", () => {
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new Error("blocked");
      });

      expect(api.clearApiKey()).toBe(false);

      expect(api.getApiKey()).toBeNull();
      expect(requestInterceptor({ headers: {} }).headers).not.toHaveProperty(
        "X-API-Key",
      );
    });

    it("reports a clear that storage accepted", () => {
      expect(api.clearApiKey()).toBe(true);
      expect(sessionStorage.getItem("autoheal_api_key")).toBeNull();
    });
  });

  describe("after a reload (a fresh module)", () => {
    afterEach(() => {
      sessionStorage.clear();
    });

    it("reads the key persisted by the previous page load", async () => {
      sessionStorage.setItem("autoheal_api_key", "persisted");
      vi.resetModules();

      const fresh = await import("./api");

      expect(fresh.getApiKey()).toBe("persisted");
    });

    it("has no key when storage cannot be read on load", async () => {
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("blocked");
      });
      vi.resetModules();

      const fresh = await import("./api");

      expect(fresh.getApiKey()).toBeNull();
      vi.restoreAllMocks();
    });

    it("has no key when nothing was persisted", async () => {
      vi.resetModules();

      const fresh = await import("./api");

      expect(fresh.getApiKey()).toBeNull();
    });
  });
});
