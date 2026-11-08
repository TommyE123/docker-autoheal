import { describe, it, expect, beforeEach, vi } from "vitest";
import axios from "axios";
import { DemoEngine } from "./engine.js";
import {
  createMockAdapter,
  handleRequest,
  trimTrailingSlashes,
} from "./mockApi.js";

// Field names of the backend's response models (app/api/models.py).
const CONTAINER_INFO_FIELDS = [
  "id",
  "name",
  "image",
  "status",
  "state",
  "labels",
  "health",
  "restart_count",
  "monitored",
  "quarantined",
  "uptime_kuma_status",
  "uptime_kuma_monitor_name",
];
const SYSTEM_STATUS_FIELDS = [
  "monitoring_active",
  "docker_connected",
  "total_containers",
  "monitored_containers",
  "quarantined_containers",
  "maintenance_mode",
  "maintenance_start_time",
  "config",
];

const T0 = Date.parse("2026-01-01T12:00:00Z");
let now;
let engine;
let api;

const error = async (promise) => {
  try {
    await promise;
  } catch (e) {
    return e;
  }
  throw new Error("expected the request to fail");
};

beforeEach(() => {
  now = T0;
  engine = new DemoEngine({ clock: () => now });
  api = axios.create({ baseURL: "/api", adapter: createMockAdapter(engine) });
});

describe("status and containers", () => {
  it("returns SystemStatus", async () => {
    const { data, status } = await api.get("/status");
    expect(status).toBe(200);
    expect(Object.keys(data).sort()).toEqual([...SYSTEM_STATUS_FIELDS].sort());
    expect(data).toMatchObject({
      monitoring_active: false,
      docker_connected: true,
      total_containers: 6,
      monitored_containers: 5,
      quarantined_containers: 0,
      maintenance_mode: false,
      maintenance_start_time: null,
    });
    expect(data.config.monitor.interval_seconds).toBe(5);
    engine.start();
    expect((await api.get("/status")).data.monitoring_active).toBe(true);
    engine.stop();
  });

  it("lists ContainerInfo, running only unless include_stopped", async () => {
    const running = (await api.get("/containers")).data;
    expect(running.map((c) => c.name)).not.toContain("nightly-backup");
    const all = (
      await api.get("/containers", { params: { include_stopped: true } })
    ).data;
    expect(all).toHaveLength(6);
    for (const container of all) {
      expect(Object.keys(container).sort()).toEqual(
        [...CONTAINER_INFO_FIELDS].sort(),
      );
    }
    expect(all.find((c) => c.name === "grafana")).toMatchObject({
      monitored: false,
      uptime_kuma_status: 5,
      uptime_kuma_monitor_name: null,
    });
    engine.config.uptime_kuma.enabled = true;
    expect((await api.get("/containers")).data[0].uptime_kuma_status).toBe(4);
  });

  it("returns container details by ID prefix or name, 404 otherwise", async () => {
    const { data } = await api.get("/containers/shop-web-1");
    expect(data).toMatchObject({
      name: "shop-web-1",
      monitored: true,
      quarantined: false,
      recent_restart_count: 0,
      total_restart_count: 0,
      restart_count: 0,
      custom_health_check: null,
      stable_id: "shop_web",
    });
    expect((await api.get(`/containers/${data.id}`)).data.name).toBe(
      "shop-web-1",
    );
    const e = await error(api.get("/containers/missing"));
    expect(e.response.status).toBe(404);
    expect(e.response.data).toEqual({ detail: "Container not found" });
  });

  it("selects and excludes containers by stable ID", async () => {
    const res = await api.post("/containers/select", {
      container_ids: ["grafana", "unknown"],
      enabled: true,
    });
    expect(res.data).toEqual({
      status: "success",
      message: "Updated 2 containers",
    });
    expect(engine.config.containers.selected).toEqual(["grafana", "unknown"]);
    await api.post("/containers/select", {
      container_ids: ["grafana", "unknown"],
      enabled: false,
    });
    expect(engine.config.containers.selected).toEqual([]);
    expect(engine.config.containers.excluded).toEqual(["grafana", "unknown"]);
    await api.post("/containers/select", {
      container_ids: ["shop-web-1"],
      enabled: false,
    });
    expect(engine.config.containers.excluded).toContain("shop_web");
    const e = await error(api.post("/containers/select", { enabled: true }));
    expect(e.response.status).toBe(422);
  });

  it("restarts manually without counting it as an Autoheal restart", async () => {
    const res = await api.post("/containers/shop-worker-1/restart");
    expect(res.data).toEqual({
      status: "success",
      message: "Container shop-worker-1 restarted",
    });
    const details = (await api.get("/containers/shop-worker-1")).data;
    expect(details.status).toBe("running");
    expect(details.total_restart_count).toBe(0);
    expect(engine.events).toEqual([]);
    expect(
      (await error(api.post("/containers/nope/restart"))).response.status,
    ).toBe(404);
  });

  it("un-quarantines, clearing history and logging an event", async () => {
    engine.quarantined.add("compose:shop:worker#1");
    engine.recordRestart("compose:shop:worker#1");
    const res = await api.post("/containers/shop-worker-1/unquarantine");
    expect(res.data.message).toBe(
      "Container shop-worker-1 removed from quarantine",
    );
    expect(engine.quarantined.size).toBe(0);
    expect(engine.totalRestartCount("compose:shop:worker#1")).toBe(0);
    expect(engine.events.at(-1)).toMatchObject({
      event_type: "unquarantine",
      container_name: "shop-worker-1 (compose:shop:worker#1)",
      message: "Container un-quarantined by user request",
    });
  });

  it("serves /health to the global axios too", async () => {
    const res = await axios.get("/health", {
      adapter: createMockAdapter(engine),
    });
    expect(res.data).toMatchObject({
      status: "healthy",
      docker_connected: true,
    });
    expect(res.data.timestamp).toBe("2026-01-01T12:00:00.000Z");
  });
});

describe("maintenance", () => {
  it("enables, reports and disables maintenance mode", async () => {
    const on = (await api.post("/maintenance/enable")).data;
    expect(on).toMatchObject({
      maintenance_mode: true,
      maintenance_start_time: "2026-01-01T12:00:00.000Z",
    });
    expect((await api.get("/maintenance/status")).data.maintenance_mode).toBe(
      true,
    );
    expect((await api.get("/status")).data.maintenance_mode).toBe(true);
    const off = (await api.post("/maintenance/disable")).data;
    expect(off).toEqual({
      status: "success",
      message: "Maintenance mode disabled",
      maintenance_mode: false,
    });
    expect((await api.get("/maintenance/status")).data).toEqual({
      maintenance_mode: false,
      maintenance_start_time: null,
    });
  });
});

describe("configuration", () => {
  it("updates monitor and restart settings, filling defaults", async () => {
    await api.put("/config/monitor", { interval_seconds: "10" });
    expect(engine.config.monitor).toEqual({
      interval_seconds: 10,
      label_key: "autoheal",
      label_value: "true",
      include_all: false,
    });
    await api.put("/config/restart", {
      mode: "health",
      backoff: { enabled: false },
    });
    expect(engine.config.restart).toMatchObject({
      mode: "health",
      cooldown_seconds: 60,
      backoff: { enabled: false, initial_seconds: 10 },
    });
  });

  it("rejects invalid values with FastAPI's 422 body", async () => {
    const e = await error(
      api.put("/config/monitor", {
        interval_seconds: 0,
        include_all: "maybe",
        label_key: 3,
      }),
    );
    expect(e.response.status).toBe(422);
    expect(e.response.data.detail.map((d) => d.loc)).toEqual([
      ["body", "interval_seconds"],
      ["body", "label_key"],
      ["body", "include_all"],
    ]);
    const restart = await error(
      api.put("/config/restart", {
        max_restarts: 1.5,
        backoff: { multiplier: "x" },
      }),
    );
    expect(restart.response.data.detail.map((d) => d.loc)).toEqual([
      ["body", "max_restarts"],
      ["body", "backoff", "multiplier"],
    ]);
    expect(
      (await error(api.put("/config/monitor", "nope"))).response.status,
    ).toBe(422);
    expect(engine.config.monitor.interval_seconds).toBe(5);
  });

  it("accepts lax booleans like Pydantic", async () => {
    await api.put("/config/monitor", { include_all: "true" });
    expect(engine.config.monitor.include_all).toBe(true);
    await api.put("/config/monitor", { include_all: 0 });
    expect(engine.config.monitor.include_all).toBe(false);
    expect(
      (await error(api.put("/config/monitor", { interval_seconds: true })))
        .response.status,
    ).toBe(422);
  });

  it("replaces the whole config but keeps live restart counts", async () => {
    engine.recordRestart("x");
    const config = (await api.get("/config")).data;
    config.monitor.label_key = "heal";
    config.containers.restart_counts = {};
    config.unknown = 1;
    expect((await api.put("/config", config)).data.message).toBe(
      "Configuration updated",
    );
    expect(engine.config.monitor.label_key).toBe("heal");
    expect(engine.config.containers.restart_counts).toEqual({ x: 1 });
    expect(engine.config.unknown).toBeUndefined();
    expect((await error(api.put("/config", [1]))).response.status).toBe(422);
  });

  it("updates observability settings", async () => {
    await api.put("/config/observability", { log_level: "DEBUG", other: 1 });
    expect(engine.config.observability.log_level).toBe("DEBUG");
    expect(engine.config.observability.other).toBeUndefined();
  });

  it("exports and imports the config with custom health checks", async () => {
    engine.customHealthChecks.shop_web = {
      container_id: "shop_web",
      check_type: "tcp",
      tcp_port: 80,
    };
    const exported = (await api.get("/config/export")).data;
    expect(exported.custom_health_checks.shop_web.check_type).toBe("tcp");
    exported.monitor.label_key = "imported";

    engine.reset();
    const form = new FormData();
    form.append("file", new File([JSON.stringify(exported)], "config.json"));
    const res = await api.post("/config/import", form);
    expect(res.data.message).toBe("Configuration imported successfully");
    expect(engine.config.monitor.label_key).toBe("imported");
    expect(engine.customHealthChecks.shop_web.tcp_port).toBe(80);
  });

  it("refuses an invalid import without changing anything", async () => {
    const bad = new FormData();
    bad.append("file", new File(["{not json"], "c.json"));
    const notJson = await error(api.post("/config/import", bad));
    expect(notJson.response.status).toBe(422);
    expect(notJson.response.data).toEqual({ detail: "File is not valid JSON" });
    const invalid = new FormData();
    invalid.append(
      "file",
      new File(
        [JSON.stringify({ monitor: { interval_seconds: 0 } })],
        "c.json",
      ),
    );
    const e = await error(api.post("/config/import", invalid));
    expect(e.response.status).toBe(422);
    expect(e.response.data.detail).toBe(
      "monitor.interval_seconds: Input should be greater than or equal to 1",
    );
    const badChecks = new FormData();
    badChecks.append(
      "file",
      new File([JSON.stringify({ custom_health_checks: { a: 1 } })], "c.json"),
    );
    expect(
      (await error(api.post("/config/import", badChecks))).response.data,
    ).toEqual({
      detail:
        "custom_health_checks must be an object whose values are health check objects",
    });
    const badCheck = new FormData();
    badCheck.append(
      "file",
      new File(
        [
          JSON.stringify({
            custom_health_checks: {
              a: { container_id: "a", check_type: "ping" },
            },
          }),
        ],
        "c.json",
      ),
    );
    expect(
      (await error(api.post("/config/import", badCheck))).response.data,
    ).toEqual({
      detail:
        "Value error, Unknown check_type; expected one of: http, tcp, exec, docker",
    });
    expect(engine.config.monitor.interval_seconds).toBe(5);
    expect((await error(api.post("/config/import", {}))).response.status).toBe(
      422,
    );
  });
});

describe("custom health checks", () => {
  it("adds, reads and removes a check by stable ID", async () => {
    const res = await api.post("/healthchecks", {
      container_id: "shop-web-1",
      check_type: "http",
      http_endpoint: "/health",
    });
    expect(res.data.message).toBe("Health check added for container shop_web");
    expect((await api.get("/healthchecks")).data.shop_web).toMatchObject({
      container_id: "shop_web",
      interval_seconds: 30,
      http_expected_status: 200,
    });
    expect((await api.get("/healthchecks/shop-web-1")).data.check_type).toBe(
      "http",
    );
    expect(
      (await api.get("/containers/shop-web-1")).data.custom_health_check
        .check_type,
    ).toBe("http");
    await api.delete("/healthchecks/shop-web-1");
    const e = await error(api.get("/healthchecks/shop-web-1"));
    expect(e.response.data.detail).toBe(
      "No custom health check found for this container",
    );
  });

  it("validates checks like HealthCheckConfig", async () => {
    const cases = [
      [{ check_type: "http" }, "container_id is required"],
      [{ container_id: "x", check_type: "ping" }, "Unknown check_type"],
      [{ container_id: "x", check_type: "tcp" }, "requires: tcp_port"],
      [
        { container_id: "x", check_type: "http", http_endpoint: " " },
        "must not be empty",
      ],
      [
        { container_id: "x", check_type: "tcp", tcp_port: 70000 },
        "between 1 and 65535",
      ],
      [
        { container_id: "x", check_type: "exec", exec_command: [] },
        "non-empty list",
      ],
    ];
    for (const [body, message] of cases) {
      const e = await error(api.post("/healthchecks", body));
      expect(e.response.status).toBe(422);
      expect(e.response.data.detail[0].msg).toContain(message);
    }
    const missing = await error(
      api.post("/healthchecks", { container_id: "nope", check_type: "docker" }),
    );
    expect(missing.response.status).toBe(404);
  });
});

describe("events", () => {
  beforeEach(() => {
    for (const [type, name] of [
      ["restart", "shop-web-1"],
      ["quarantine", "shop-api-1"],
      ["restart", "shop-api-1"],
    ]) {
      engine.addEvent({
        container_name: `${name} (x)`,
        container_id: "id",
        event_type: type,
        restart_count: 1,
        status: "success",
        message: "m",
      });
    }
  });

  it("filters by type and container before the limit", async () => {
    expect((await api.get("/events")).data).toHaveLength(3);
    expect(
      (await api.get("/events", { params: { event_type: "restart" } })).data,
    ).toHaveLength(2);
    const api1 = (
      await api.get("/events", { params: { container: "API", limit: 1 } })
    ).data;
    expect(api1).toHaveLength(1);
    expect(api1[0].event_type).toBe("restart");
    expect(Object.keys(api1[0]).sort()).toEqual(
      [
        "timestamp",
        "container_id",
        "container_name",
        "event_type",
        "restart_count",
        "status",
        "message",
      ].sort(),
    );
    expect((await api.get("/events?limit=2")).data).toHaveLength(2);
    expect(
      (await error(api.get("/events", { params: { limit: 0 } }))).response
        .status,
    ).toBe(422);
  });

  it("clears the log", async () => {
    expect((await api.delete("/events")).data).toEqual({
      status: "success",
      message: "All events cleared",
    });
    expect((await api.get("/events")).data).toEqual([]);
  });
});

describe("notifications", () => {
  const service = {
    name: "chat",
    type: "discord",
    url: "https://example.invalid",
    headers: { "X-Demo": "1" },
  };

  it("adds, updates, tests and deletes services", async () => {
    const added = (await api.post("/notifications/services", service)).data;
    expect(added.service).toMatchObject({
      name: "chat",
      enabled: true,
      url: "https://example.invalid",
      bot_token: null,
    });
    expect(
      (await error(api.post("/notifications/services", service))).response.data
        .detail,
    ).toBe("Service with name 'chat' already exists");
    const updated = (
      await api.put("/notifications/services/chat", {
        type: "slack",
        enabled: false,
      })
    ).data;
    expect(updated.service).toMatchObject({
      name: "chat",
      type: "slack",
      enabled: false,
    });
    expect(
      (await error(api.post("/notifications/test/chat"))).response.data.detail,
    ).toBe("Service 'chat' is disabled");
    await api.put("/notifications/services/chat", { type: "slack" });
    expect((await api.post("/notifications/test/chat")).data.message).toContain(
      "Demo: nothing was sent",
    );
    expect((await api.post("/notifications/test", service)).data.status).toBe(
      "success",
    );
    await api.delete("/notifications/services/chat");
    expect(
      (await error(api.delete("/notifications/services/chat"))).response.status,
    ).toBe(404);
    expect(
      (await error(api.put("/notifications/services/chat", {}))).response
        .status,
    ).toBe(404);
    expect(
      (await error(api.post("/notifications/test/chat"))).response.data.detail,
    ).toBe("Service 'chat' not found");
  });

  it("validates services", async () => {
    const missing = await error(
      api.post("/notifications/services", { name: "x" }),
    );
    expect(missing.response.status).toBe(422);
    expect(missing.response.data).toEqual({ detail: "type: Field required" });
    await api.post("/notifications/services", service);
    const wrong = await error(
      api.put("/notifications/services/chat", {
        type: 3,
        enabled: "yes",
        headers: "x",
        url: 1,
      }),
    );
    expect(wrong.response.status).toBe(422);
    expect(wrong.response.data.detail).toBe(
      "type: Input should be a valid string; enabled: Input should be a valid boolean; url: Input should be a valid string; headers: Input should be a valid dictionary",
    );
    const e = await error(api.post("/notifications/test", { type: "slack" }));
    expect(e.response.status).toBe(422);
    expect(e.response.data.detail).toEqual([
      { loc: ["name"], msg: "Field required" },
    ]);
    expect(
      (await error(api.post("/notifications/test", "x"))).response.status,
    ).toBe(422);
    expect(
      (await error(api.post("/notifications/test", [1]))).response.status,
    ).toBe(422);
  });

  it("reads and replaces the notification config", async () => {
    expect((await api.get("/notifications/config")).data).toEqual({
      enabled: false,
      services: [],
      event_filters: [
        "restart",
        "quarantine",
        "auto_unquarantine",
        "auto_monitor",
      ],
    });
    const res = (
      await api.put("/notifications/config", {
        enabled: true,
        event_filters: [],
        services: [service],
      })
    ).data;
    expect(res.config).toMatchObject({ enabled: true, event_filters: [] });
    expect(res.config.services[0].name).toBe("chat");
    const bad = await error(
      api.put("/notifications/config", {
        enabled: "yes",
        event_filters: [1],
        services: [{}],
      }),
    );
    expect(bad.response.status).toBe(422);
    expect(bad.response.data.detail).toBe(
      "enabled: Input should be a valid boolean; event_filters.0: Input should be a valid string; services.0.name: Field required; services.0.type: Field required",
    );
    expect(
      (await error(api.put("/notifications/config", { event_filters: "x" })))
        .response.data.detail,
    ).toBe("event_filters: Input should be a valid list");
    expect(
      (await error(api.put("/notifications/config", { services: ["x"] })))
        .response.data.detail,
    ).toBe("services.0: Input should be a valid dictionary");
    expect(
      (await error(api.put("/notifications/config", "x"))).response.status,
    ).toBe(422);
  });
});

describe("Uptime Kuma", () => {
  it("explains it isn't available in the demo", async () => {
    expect((await api.post("/uptime-kuma/test-connection", {})).data).toEqual({
      success: false,
      message: "Connection error: Uptime Kuma isn't available in the demo",
    });
    expect(
      (await error(api.post("/uptime-kuma/enable", {}))).response.status,
    ).toBe(400);
    const e = await error(
      api.post("/uptime-kuma/enable", {
        server_url: "http://k",
        api_token: "t",
      }),
    );
    expect(e.response.status).toBe(500);
    expect(e.response.data).toEqual({
      detail: "Internal server error, see logs",
    });
    const invalid = await error(
      api.post("/uptime-kuma/enable", {
        server_url: "http://k",
        api_token: "t",
        username: 1,
        auto_restart_on_down: "no",
      }),
    );
    expect(invalid.response.status).toBe(422);
    expect(invalid.response.data.detail).toBe(
      "username: Input should be a valid string; auto_restart_on_down: Input should be a valid boolean",
    );
    expect(
      (await error(api.get("/uptime-kuma/monitors"))).response.data.detail,
    ).toBe("Uptime-Kuma integration not enabled");
    engine.config.uptime_kuma.enabled = true;
    expect((await api.get("/uptime-kuma/monitors")).data).toEqual({
      monitors: [],
    });
    expect((await api.post("/uptime-kuma/disable")).data).toEqual({
      success: true,
    });
    expect(engine.config.uptime_kuma.enabled).toBe(false);
  });

  it("manages mappings", async () => {
    const res = await api.post("/uptime-kuma/mappings", {
      container_id: "shop-web-1",
      monitor_friendly_name: "Web",
    });
    expect(res.data.mapping).toEqual({
      container_id: "shop_web",
      monitor_friendly_name: "Web",
      auto_mapped: false,
    });
    expect((await api.get("/uptime-kuma/mappings")).data.mappings).toHaveLength(
      1,
    );
    await api.delete("/uptime-kuma/mappings/shop_web");
    expect((await api.get("/uptime-kuma/mappings")).data.mappings).toEqual([]);
    const unknown = await error(
      api.post("/uptime-kuma/mappings", {
        container_id: "nope",
        monitor_friendly_name: "Web",
      }),
    );
    expect(unknown.response.status).toBe(404);
    expect(unknown.response.data).toEqual({ detail: "Container not found" });
    const blank = await error(
      api.post("/uptime-kuma/mappings", { container_id: "shop-web-1" }),
    );
    expect(blank.response.status).toBe(400);
    expect(blank.response.data.detail).toBe(
      "container_id and monitor_friendly_name are required",
    );
  });
});

describe("routing", () => {
  it("returns FastAPI's 404 and 405", async () => {
    const missing = await error(api.get("/nope"));
    expect(missing.response.status).toBe(404);
    expect(missing.response.data).toEqual({ detail: "Not Found" });
    expect(missing.code).toBe("ERR_BAD_REQUEST");
    expect((await error(api.patch("/config"))).response.status).toBe(405);
  });

  it("handles absolute URLs, trailing slashes and a custom validateStatus", async () => {
    const res = await handleRequest(engine, {
      url: "http://host:3131/api/status/",
    });
    expect(res.status).toBe(200);
    expect(
      (
        await handleRequest(engine, {
          baseURL: "/api/",
          url: "/maintenance/status",
        })
      ).status,
    ).toBe(200);
    const accepted = await api.get("/nope", { validateStatus: () => true });
    expect(accepted.status).toBe(404);
  });

  it("turns unexpected handler errors into the generic 500", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    engine.config.notifications = null;
    const e = await error(api.get("/notifications/config"));
    expect(e.response.status).toBe(500);
    // No internal exception text reaches the client (app/api/errors.py).
    expect(e.response.data).toEqual({
      detail: "Internal server error, see logs",
    });
    expect(e.code).toBe("ERR_BAD_RESPONSE");
    expect(consoleError).toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("notifies engine listeners after each request", async () => {
    let calls = 0;
    engine.subscribe(() => (calls += 1));
    await api.get("/status");
    expect(calls).toBe(1);
  });
});

describe("edge cases", () => {
  it("fills restart defaults when backoff is left out", async () => {
    await api.put("/config/restart", { cooldown_seconds: 5 });
    expect(engine.config.restart).toMatchObject({
      cooldown_seconds: 5,
      backoff: { enabled: true, initial_seconds: 10 },
    });
  });

  it("rejects non-object bodies", async () => {
    // FastAPI rejects a non-object body for a `dict` parameter with its 422.
    const dictError = {
      detail: [
        {
          type: "dict_type",
          loc: ["body"],
          msg: "Input should be a valid dictionary",
        },
      ],
    };
    for (const [method, url] of [
      ["post", "/notifications/services"],
      ["put", "/notifications/services/c"],
      ["put", "/notifications/config"],
      ["put", "/config/observability"],
      ["post", "/uptime-kuma/enable"],
      ["post", "/uptime-kuma/mappings"],
    ]) {
      const e = await error(api[method](url, [1]));
      expect(e.response.status).toBe(422);
      expect(e.response.data).toEqual(dictError);
    }
    expect((await error(api.post("/healthchecks", [1]))).response.status).toBe(
      422,
    );
    expect(
      (await error(api.put("/notifications/config", { services: "x" })))
        .response.data.detail,
    ).toBe("services: Input should be a valid list");
  });

  it("refuses an import that isn't a JSON object", async () => {
    const form = new FormData();
    form.append("file", new File(["[1]"], "c.json"));
    const e = await error(api.post("/config/import", form));
    expect(e.response.status).toBe(422);
    expect(e.response.data).toEqual({
      detail: "Configuration must be a JSON object",
    });
  });

  it("deletes a check stored under the full Docker ID", async () => {
    const { full_id: fullId } = (await api.get("/containers/shop-web-1")).data;
    engine.customHealthChecks[fullId] = { check_type: "docker" };
    expect((await api.get("/healthchecks/shop-web-1")).data.check_type).toBe(
      "docker",
    );
    await api.delete("/healthchecks/shop-web-1");
    expect(engine.customHealthChecks).toEqual({});
  });

  it("handles a missing or root URL", async () => {
    expect((await handleRequest(engine, {})).status).toBe(404);
    expect((await handleRequest(engine, { url: "/" })).status).toBe(404);
  });

  it("uses axios's default status check when the config has none", async () => {
    const adapter = createMockAdapter(engine);
    expect((await adapter({ url: "/api/status" })).status).toBe(200);
    await expect(adapter({ url: "/api/nope" })).rejects.toThrow(
      "Request failed with status code 404",
    );
  });

  it("rejects malformed config sections like AutoHealConfig", async () => {
    const config = (await api.get("/config")).data;
    config.uptime_kuma_mappings = "x";
    config.ui = "x";
    const e = await error(api.put("/config", config));
    expect(e.response.status).toBe(422);
    expect(e.response.data.detail.map((d) => d.loc)).toEqual([
      ["body", "ui"],
      ["body", "uptime_kuma_mappings"],
    ]);
    expect(engine.config.ui.listen_port).toBe(3131);
  });

  it("doesn't duplicate an already selected container", async () => {
    const body = { container_ids: ["grafana", "unknown"], enabled: true };
    await api.post("/containers/select", body);
    await api.post("/containers/select", body);
    expect(engine.config.containers.selected).toEqual(["grafana", "unknown"]);
  });

  it("updates only the notification fields that are sent", async () => {
    await api.put("/notifications/config", { enabled: true });
    expect(engine.config.notifications.enabled).toBe(true);
    await api.put("/notifications/config", {
      services: [{ name: "c", type: "slack" }],
    });
    expect(engine.config.notifications).toMatchObject({
      enabled: true,
      event_filters: [
        "restart",
        "quarantine",
        "auto_unquarantine",
        "auto_monitor",
      ],
    });
    expect(engine.config.notifications.services).toHaveLength(1);
  });

  it("trims any number of trailing slashes", () => {
    expect(trimTrailingSlashes("/a/b//")).toBe("/a/b");
    expect(trimTrailingSlashes("/a")).toBe("/a");
    expect(trimTrailingSlashes("///")).toBe("");
  });

  it("rejects wrongly typed fields in the other sections, like AutoHealConfig", async () => {
    const config = (await api.get("/config")).data;
    config.filters.blacklist_names = "abc";
    config.ui.max_log_entries = "lots";
    const e = await error(api.put("/config", config));
    expect(e.response.status).toBe(422);
    expect(e.response.data.detail).toEqual([
      {
        type: "list_type",
        loc: ["body", "filters", "blacklist_names"],
        msg: "Input should be a valid list",
      },
      {
        type: "number_type",
        loc: ["body", "ui", "max_log_entries"],
        msg: "Input should be a valid number",
      },
    ]);
    expect(engine.config.filters.blacklist_names).toEqual([]);

    const form = new FormData();
    form.append(
      "file",
      new File(
        [JSON.stringify({ filters: { blacklist_names: "abc" } })],
        "c.json",
      ),
    );
    const imported = await error(api.post("/config/import", form));
    expect(imported.response.status).toBe(422);
    expect(imported.response.data).toEqual({
      detail: "filters.blacklist_names: Input should be a valid list",
    });
    // The simulation keeps working after the rejected payloads.
    expect(() => engine.runCycle()).not.toThrow();
  });

  it("drops unknown fields and lets optional (null) fields take a value", async () => {
    const config = (await api.get("/config")).data;
    config.filters.unknown = 1;
    config.alerts.webhook = "https://example.invalid/hook";
    await api.put("/config", config);
    expect(engine.config.filters.unknown).toBeUndefined();
    expect(engine.config.alerts.webhook).toBe("https://example.invalid/hook");
  });

  it("validates observability settings like ObservabilityConfig", async () => {
    const e = await error(
      api.put("/config/observability", {
        log_level: 3,
        prometheus_enabled: "yes",
      }),
    );
    expect(e.response.status).toBe(422);
    expect(e.response.data.detail).toBe(
      "log_level: Input should be a valid string; prometheus_enabled: Input should be a valid boolean",
    );
    expect(engine.config.observability.log_level).toBe("INFO");
  });
});
