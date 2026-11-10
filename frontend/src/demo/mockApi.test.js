import { describe, it, expect, beforeEach } from "vitest";
import axios from "axios";
import {
  createDemoState,
  createMockAdapter,
  handleRequest,
} from "./mockApi.js";

let state;
let api;

const failure = (promise) =>
  promise.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (error) => error.response,
  );

beforeEach(() => {
  state = createDemoState();
  api = axios.create({ baseURL: "/api", adapter: createMockAdapter(state) });
});

describe("demo mock API", () => {
  it("serves the status and the sample containers", async () => {
    const status = (await api.get("/status")).data;
    expect(status).toMatchObject({
      total_containers: 6,
      monitored_containers: 5,
      quarantined_containers: 1,
      maintenance_mode: false,
    });
    expect((await api.get("/containers")).data).toHaveLength(4);
    const all = (
      await api.get("/containers", { params: { include_stopped: true } })
    ).data;
    expect(all.map((c) => c.name)).toEqual([
      "web",
      "api",
      "worker",
      "db",
      "backup",
      "grafana",
    ]);
    expect((await api.get("/containers/worker")).data).toMatchObject({
      quarantined: true,
      recent_restart_count: 3,
    });
    expect((await failure(api.get("/containers/nope"))).status).toBe(404);
  });

  it("applies the container actions", async () => {
    await api.post("/containers/select", {
      container_ids: ["grafana"],
      enabled: true,
    });
    expect(state.containers[5].monitored).toBe(true);
    await api.post("/containers/backup/restart");
    expect(state.containers[4].status).toBe("running");
    await api.post("/containers/worker/unquarantine");
    expect(state.containers[2].quarantined).toBe(false);
    expect(state.events.at(-1).event_type).toBe("unquarantine");
  });

  it("toggles maintenance mode", async () => {
    await api.post("/maintenance/enable");
    expect((await api.get("/status")).data.maintenance_mode).toBe(true);
    await api.post("/maintenance/disable");
    expect((await api.get("/status")).data.maintenance_mode).toBe(false);
  });

  it("saves, exports and imports settings", async () => {
    await api.put("/config/monitor", { interval_seconds: 10 });
    await api.put("/config/observability", { log_level: "DEBUG" });
    const exported = (await api.get("/config/export")).data;
    expect(exported.monitor.interval_seconds).toBe(10);
    expect((await api.get("/config")).data.observability.log_level).toBe(
      "DEBUG",
    );

    const form = new FormData();
    form.append(
      "file",
      new File([JSON.stringify({ ui: { listen_port: 4000 } })], "c.json"),
    );
    await api.post("/config/import", form);
    expect(state.config.ui).toEqual({ listen_port: 4000 });

    const bad = new FormData();
    bad.append("file", new File(["{not json"], "c.json"));
    expect((await failure(api.post("/config/import", bad))).status).toBe(422);
  });

  it("filters and clears the events", async () => {
    expect((await api.get("/events")).data).toHaveLength(5);
    const params = { event_type: "restart", container: "work", limit: 2 };
    expect((await api.get("/events", { params })).data).toHaveLength(2);
    await api.delete("/events");
    expect((await api.get("/events")).data).toEqual([]);
  });

  it("manages notification services without sending anything", async () => {
    await api.put("/notifications/config", { enabled: false });
    expect((await api.get("/notifications/config")).data.enabled).toBe(false);
    await api.post("/notifications/services", { name: "ops", type: "slack" });
    await api.put("/notifications/services/ops", { enabled: false });
    expect(state.config.notifications.services[1]).toEqual({
      name: "ops",
      type: "slack",
      enabled: false,
    });
    await api.delete("/notifications/services/Team%20chat");
    expect(state.config.notifications.services).toHaveLength(1);
    for (const url of ["/notifications/test", "/notifications/test/ops"]) {
      expect((await api.post(url, {})).data.message).toContain("Demo");
    }
  });

  it("explains that Uptime Kuma isn't available", async () => {
    expect((await api.post("/uptime-kuma/test-connection", {})).data).toEqual({
      success: false,
      message: "Uptime Kuma isn't available in the demo",
    });
    expect((await failure(api.post("/uptime-kuma/enable", {}))).status).toBe(
      400,
    );
    expect((await api.get("/uptime-kuma/monitors")).data).toEqual({
      monitors: [],
    });
    expect((await api.get("/uptime-kuma/mappings")).data).toEqual({
      mappings: [],
    });
    expect((await api.post("/uptime-kuma/disable")).data).toEqual({
      success: true,
    });
  });

  it("answers /health and 404s unknown routes", async () => {
    expect((await handleRequest(state, { url: "/health" })).status).toBe(200);
    expect(
      (await handleRequest(state, { method: "patch", url: "/api/config" }))
        .data,
    ).toEqual({ detail: "Not Found" });
  });

  it("lets unexpected errors through", async () => {
    await expect(
      api.post("/containers/select", { enabled: true }),
    ).rejects.toThrow(TypeError);
  });
});
