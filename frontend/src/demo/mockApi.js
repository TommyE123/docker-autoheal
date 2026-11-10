// Demo-only stand-in for the backend, as an axios adapter.
//
// The demo exists so visitors can see the real UI and click around it. This
// answers the API calls the UI makes with fixed sample data and simple
// changes to it (enable a container, clear the events, save a setting, ...).
// It deliberately doesn't validate input or simulate the monitoring engine.
// Everything lives in memory, so a page reload starts again.

import { AxiosError } from "axios";
import defaultConfig from "./default-config.json";

const clone = (value) => JSON.parse(JSON.stringify(value));
const minutesAgo = (minutes) =>
  new Date(Date.now() - minutes * 60000).toISOString();

// A sample container's 64-character ID, from its position in the list.
const fullId = (index) => String(index).repeat(64);

const DEMO_MESSAGE =
  "Demo: nothing was sent. A real install would contact the service.";

function sampleContainer(index, name, image, options = {}) {
  const {
    status = "running",
    health = "healthy",
    monitored = true,
    quarantined = false,
    restarts = 0,
    exitCode = 0,
  } = options;
  return {
    id: fullId(index).slice(0, 12),
    full_id: fullId(index),
    name,
    image,
    status,
    state: { Status: status, ExitCode: exitCode },
    labels: monitored ? { autoheal: "true" } : {},
    health: health ? { status: health, failing_streak: 0 } : null,
    restart_count: restarts,
    recent_restart_count: restarts,
    exit_code: exitCode,
    monitored,
    quarantined,
    uptime_kuma_status: 5,
    uptime_kuma_monitor_name: null,
  };
}

function sampleEvent(
  minutes,
  containerId,
  name,
  type,
  status,
  restarts,
  message,
) {
  return {
    timestamp: minutesAgo(minutes),
    container_id: containerId,
    container_name: name,
    event_type: type,
    restart_count: restarts,
    status,
    message,
  };
}

/** The sample data the demo starts with. */
export function createDemoState() {
  const config = clone(defaultConfig);
  config.notifications.enabled = true;
  config.notifications.services = [
    {
      name: "Team chat",
      type: "discord",
      enabled: true,
      url: "https://discord.example/webhook",
    },
  ];
  return {
    config,
    maintenance: { mode: false, start: null },
    containers: [
      sampleContainer(1, "web", "nginx:1.27-alpine"),
      sampleContainer(2, "api", "example/shop-api:2.3", { restarts: 1 }),
      sampleContainer(3, "worker", "example/shop-worker:2.3", {
        status: "exited",
        health: null,
        quarantined: true,
        restarts: 3,
        exitCode: 1,
      }),
      sampleContainer(4, "db", "postgres:16-alpine"),
      sampleContainer(5, "backup", "alpine:3.20", {
        status: "exited",
        health: null,
      }),
      sampleContainer(6, "grafana", "grafana/grafana:11.3", {
        monitored: false,
      }),
    ],
    events: [
      sampleEvent(
        42,
        fullId(2),
        "api",
        "restart",
        "success",
        1,
        "Restart successful: Docker health check reports unhealthy",
      ),
      sampleEvent(
        30,
        fullId(3),
        "worker",
        "restart",
        "success",
        1,
        "Restart successful: Container exited with code 1",
      ),
      sampleEvent(
        25,
        fullId(3),
        "worker",
        "restart",
        "success",
        2,
        "Restart successful: Container exited with code 1",
      ),
      sampleEvent(
        15,
        fullId(3),
        "worker",
        "restart",
        "success",
        3,
        "Restart successful: Container exited with code 1",
      ),
      sampleEvent(
        10,
        fullId(3),
        "worker",
        "quarantine",
        "quarantined",
        3,
        "Container quarantined: exceeded 3 restarts in 600s window",
      ),
    ],
  };
}

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function findContainer(state, id) {
  const container = state.containers.find(
    (c) => c.id === id || c.full_id === id || c.name === id,
  );
  if (!container) throw new ApiError(404, "Container not found");
  return container;
}

// The fields GET /api/containers returns (ContainerInfo); details add more.
const LIST_FIELDS = [
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
const listView = (container) =>
  Object.fromEntries(LIST_FIELDS.map((field) => [field, container[field]]));

const routes = [
  [
    "get",
    "/health",
    () => ({
      status: "healthy",
      docker_connected: true,
      monitoring_active: true,
    }),
  ],
  [
    "get",
    "/api/status",
    (state) => ({
      monitoring_active: true,
      docker_connected: true,
      total_containers: state.containers.length,
      monitored_containers: state.containers.filter((c) => c.monitored).length,
      quarantined_containers: state.containers.filter((c) => c.quarantined)
        .length,
      maintenance_mode: state.maintenance.mode,
      maintenance_start_time: state.maintenance.start,
      config: clone(state.config),
    }),
  ],
  [
    "get",
    "/api/containers",
    (state, { params }) =>
      state.containers
        .filter(
          (c) =>
            String(params.include_stopped) === "true" || c.status === "running",
        )
        .map(listView),
  ],
  [
    "post",
    "/api/containers/select",
    (state, { body }) => {
      for (const id of body.container_ids) {
        findContainer(state, id).monitored = body.enabled;
      }
      return {
        status: "success",
        message: `Updated ${body.container_ids.length} containers`,
      };
    },
  ],
  [
    "get",
    "/api/containers/:id",
    (state, { id }) => clone(findContainer(state, id)),
  ],
  [
    "post",
    "/api/containers/:id/restart",
    (state, { id }) => {
      const container = findContainer(state, id);
      container.status = "running";
      container.state = { Status: "running", ExitCode: 0 };
      return { status: "success", message: `Container ${id} restarted` };
    },
  ],
  [
    "post",
    "/api/containers/:id/unquarantine",
    (state, { id }) => {
      const container = findContainer(state, id);
      container.quarantined = false;
      state.events.push(
        sampleEvent(
          0,
          container.full_id,
          container.name,
          "unquarantine",
          "success",
          0,
          "Container un-quarantined by user request",
        ),
      );
      return {
        status: "success",
        message: `Container ${container.name} removed from quarantine`,
      };
    },
  ],
  [
    "post",
    "/api/maintenance/enable",
    (state) => {
      state.maintenance = { mode: true, start: new Date().toISOString() };
      return {
        status: "success",
        maintenance_mode: true,
        maintenance_start_time: state.maintenance.start,
      };
    },
  ],
  [
    "post",
    "/api/maintenance/disable",
    (state) => {
      state.maintenance = { mode: false, start: null };
      return { status: "success", maintenance_mode: false };
    },
  ],
  ["get", "/api/config", (state) => clone(state.config)],
  ["get", "/api/config/export", (state) => clone(state.config)],
  [
    "put",
    "/api/config/:section",
    (state, { id, body }) => {
      Object.assign(state.config[id], body);
      return { status: "success", message: "Configuration updated" };
    },
  ],
  [
    "post",
    "/api/config/import",
    async (state, { body }) => {
      try {
        Object.assign(state.config, JSON.parse(await body.get("file").text()));
      } catch {
        throw new ApiError(422, "File is not valid JSON");
      }
      return {
        status: "success",
        message: "Configuration imported successfully",
      };
    },
  ],
  [
    "get",
    "/api/events",
    (state, { params }) =>
      state.events
        .filter((e) => !params.event_type || e.event_type === params.event_type)
        .filter(
          (e) =>
            !params.container || e.container_name.includes(params.container),
        )
        .slice(-(params.limit ?? 100)),
  ],
  [
    "delete",
    "/api/events",
    (state) => {
      state.events = [];
      return { status: "success", message: "All events cleared" };
    },
  ],
  [
    "get",
    "/api/notifications/config",
    (state) => clone(state.config.notifications),
  ],
  [
    "put",
    "/api/notifications/config",
    (state, { body }) => {
      Object.assign(state.config.notifications, body);
      return { status: "success", config: clone(state.config.notifications) };
    },
  ],
  [
    "post",
    "/api/notifications/services",
    (state, { body }) => {
      state.config.notifications.services.push(body);
      return { status: "success", service: body };
    },
  ],
  [
    "put",
    "/api/notifications/services/:id",
    (state, { id, body }) => {
      const services = state.config.notifications.services;
      const index = services.findIndex((s) => s.name === id);
      services[index] = { ...services[index], ...body };
      return { status: "success", service: services[index] };
    },
  ],
  [
    "delete",
    "/api/notifications/services/:id",
    (state, { id }) => {
      const notifications = state.config.notifications;
      notifications.services = notifications.services.filter(
        (s) => s.name !== id,
      );
      return { status: "success" };
    },
  ],
  [
    "post",
    "/api/notifications/test",
    () => ({ status: "success", message: DEMO_MESSAGE }),
  ],
  [
    "post",
    "/api/notifications/test/:id",
    () => ({ status: "success", message: DEMO_MESSAGE }),
  ],
  [
    "post",
    "/api/uptime-kuma/test-connection",
    () => ({
      success: false,
      message: "Uptime Kuma isn't available in the demo",
    }),
  ],
  [
    "post",
    "/api/uptime-kuma/enable",
    () => {
      throw new ApiError(400, "Uptime Kuma isn't available in the demo");
    },
  ],
  ["get", "/api/uptime-kuma/monitors", () => ({ monitors: [] })],
  ["get", "/api/uptime-kuma/mappings", () => ({ mappings: [] })],
  ["post", "/api/uptime-kuma/disable", () => ({ success: true })],
].map(([method, path, handler]) => [
  method,
  new RegExp(
    `^${path
      .replace(":id", "([^/]+)")
      .replace(":section", "(monitor|restart|observability)")}$`,
  ),
  handler,
]);

/** Answer one request from the demo state: resolves to {status, data}. */
export async function handleRequest(state, config) {
  const base = (config.baseURL ?? "").replace(/\/$/, "");
  const [path, query = ""] = `${base}/${config.url.replace(/^\//, "")}`.split(
    "?",
  );
  const method = (config.method ?? "get").toLowerCase();
  const route = routes.find(
    ([m, pattern]) => m === method && pattern.test(path),
  );
  if (!route) return { status: 404, data: { detail: "Not Found" } };
  const params = {
    ...Object.fromEntries(new URLSearchParams(query)),
    ...config.params,
  };
  const body =
    typeof config.data === "string" ? JSON.parse(config.data) : config.data;
  const id = decodeURIComponent(path.match(route[1])[1] ?? "");
  try {
    return { status: 200, data: await route[2](state, { id, params, body }) };
  } catch (error) {
    if (error instanceof ApiError) {
      return { status: error.status, data: { detail: error.detail } };
    }
    throw error;
  }
}

/** An axios adapter that answers every request from the demo state. */
export function createMockAdapter(state) {
  return async function demoAdapter(config) {
    const { status, data } = await handleRequest(state, config);
    const response = {
      data,
      status,
      statusText: "",
      headers: {},
      config,
      request: {},
    };
    if (status < 400) return response;
    throw new AxiosError(
      `Request failed with status code ${status}`,
      AxiosError.ERR_BAD_REQUEST,
      config,
      response.request,
      response,
    );
  };
}
