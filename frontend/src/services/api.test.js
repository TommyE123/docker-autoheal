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

beforeEach(() => {
  mockInstance.get.mockClear();
  mockInstance.post.mockClear();
  mockInstance.put.mockClear();
  mockInstance.delete.mockClear();
  axios.get.mockClear();
});

describe("api service", () => {
  it("creates the axios instance with a JSON content type and no-cache headers", () => {
    expect(axios.create).toHaveBeenCalledWith(
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "Cache-Control": "no-cache, no-store, must-revalidate",
        }),
      }),
    );
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
});
