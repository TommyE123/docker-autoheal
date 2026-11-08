// Demo-only stand-in for the FastAPI backend, as an axios adapter.
//
// Each handler mirrors the route of the same path in app/api/routes/, with
// the same response shape, status codes and error body ({"detail": ...}, or a
// list of {loc, msg, type} for request validation, as FastAPI returns). The
// state lives in a DemoEngine (./engine.js). When a route or its response
// changes, change it here in the same release.

import { AxiosError } from "axios";
import defaultConfig from "./default-config.json";

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "Validation error");
    this.status = status;
    this.detail = detail;
  }
}

const clone = (value) => JSON.parse(JSON.stringify(value));
const isObject = (value) =>
  typeof value === "object" && value !== null && !Array.isArray(value);

// --- request body validation (the Pydantic models' constraints) -----------

const MONITOR_FIELDS = {
  interval_seconds: { type: "int", ge: 1 },
  label_key: { type: "str" },
  label_value: { type: "str" },
  include_all: { type: "bool" },
};
const RESTART_FIELDS = {
  mode: { type: "str" },
  cooldown_seconds: { type: "int", ge: 0 },
  max_restarts: { type: "int", ge: 1 },
  max_restarts_window_seconds: { type: "int", ge: 1 },
  respect_manual_stop: { type: "bool" },
};
const BACKOFF_FIELDS = {
  enabled: { type: "bool" },
  initial_seconds: { type: "int", ge: 1 },
  multiplier: { type: "float", ge: 1 },
  max_seconds: { type: "int", ge: 1 },
};

function coerce(value, type) {
  // Pydantic's lax mode: numeric strings become numbers, "true"/"false" bools.
  if (type === "int" || type === "float") {
    const n =
      typeof value === "string" && value.trim() !== "" ? Number(value) : value;
    if (
      typeof n !== "number" ||
      Number.isNaN(n) ||
      typeof value === "boolean"
    ) {
      return {
        error: `Input should be a valid ${type === "int" ? "integer" : "number"}`,
      };
    }
    if (type === "int" && !Number.isInteger(n)) {
      return { error: "Input should be a valid integer" };
    }
    return { value: n };
  }
  if (type === "bool") {
    if (typeof value === "boolean") return { value };
    if (value === "true" || value === 1) return { value: true };
    if (value === "false" || value === 0) return { value: false };
    return { error: "Input should be a valid boolean" };
  }
  if (typeof value !== "string")
    return { error: "Input should be a valid string" };
  return { value };
}

/** Validate one model section against its fields, filling defaults. */
function validateSection(body, fields, defaults, loc, errors) {
  const result = { ...defaults };
  if (!isObject(body)) {
    errors.push({
      type: "model_type",
      loc,
      msg: "Input should be a valid dictionary",
    });
    return result;
  }
  for (const [name, rule] of Object.entries(fields)) {
    if (!(name in body)) continue;
    const { value, error } = coerce(body[name], rule.type);
    if (error) {
      errors.push({
        type: `${rule.type}_parsing`,
        loc: [...loc, name],
        msg: error,
      });
    } else if (rule.ge !== undefined && value < rule.ge) {
      errors.push({
        type: "greater_than_equal",
        loc: [...loc, name],
        msg: `Input should be greater than or equal to ${rule.ge}`,
      });
    } else {
      result[name] = value;
    }
  }
  return result;
}

function validateMonitor(body, loc, errors) {
  return validateSection(
    body,
    MONITOR_FIELDS,
    defaultConfig.monitor,
    loc,
    errors,
  );
}

function validateRestart(body, loc, errors) {
  const { backoff: defaultBackoff, ...defaults } = defaultConfig.restart;
  const restart = validateSection(body, RESTART_FIELDS, defaults, loc, errors);
  restart.backoff = validateSection(
    isObject(body) && "backoff" in body ? body.backoff : {},
    BACKOFF_FIELDS,
    defaultBackoff,
    [...loc, "backoff"],
    errors,
  );
  return restart;
}

// app/api/errors.py: the generic body of every unexpected 500.
export const INTERNAL_ERROR_DETAIL = "Internal server error, see logs";

/** FastAPI's 422 for a `dict` body parameter that isn't a JSON object. */
function requireObjectBody(body) {
  if (!isObject(body)) {
    throw new ApiError(422, [
      {
        type: "dict_type",
        loc: ["body"],
        msg: "Input should be a valid dictionary",
      },
    ]);
  }
}

/**
 * invalid_input_as_422 (app/api/errors.py): a model validation failure on
 * user data inside a handler is a 422 whose detail is one string of
 * "location: message" parts, without the submitted values.
 */
function raiseInvalidInput(errors) {
  if (!errors.length) return;
  const detail = errors
    .map(({ loc, msg }) => {
      const location = loc.filter((part) => part !== "body").join(".");
      return location ? `${location}: ${msg}` : msg;
    })
    .join("; ");
  throw new ApiError(422, detail);
}

/** Push a type error unless `value` is of `kind` (string, boolean or list). */
function checkKind(value, kind, loc, errors) {
  const ok = kind === "list" ? Array.isArray(value) : typeof value === kind;
  if (!ok) {
    const name = { string: "string", boolean: "boolean", list: "list" }[kind];
    errors.push({
      type: `${kind === "boolean" ? "bool" : kind}_type`,
      loc,
      msg: `Input should be a valid ${name}`,
    });
  }
}

function raiseIfInvalid(errors) {
  if (errors.length) throw new ApiError(422, errors);
}

// Element types of the typed collections in AutoHealConfig, keyed by
// "section.field" (config_manager.py). Each checker pushes a 422 entry for
// every bad element, as Pydantic does, and returns the value to store.
const isString = (value) => typeof value === "string";

function checkEach(items, loc, check) {
  items.forEach((item, index) => check(item, [...loc, index]));
  return clone(items);
}

function stringList(items, loc, errors) {
  return checkEach(items, loc, (item, itemLoc) =>
    checkKind(item, "string", itemLoc, errors),
  );
}

// list[dict[str, str]]
function labelFilterList(items, loc, errors) {
  return checkEach(items, loc, (item, itemLoc) => {
    if (!isObject(item)) {
      errors.push({
        type: "dict_type",
        loc: itemLoc,
        msg: "Input should be a valid dictionary",
      });
      return;
    }
    for (const [key, value] of Object.entries(item)) {
      checkKind(value, "string", [...itemLoc, key], errors);
    }
  });
}

// dict[str, int] and dict[str, list[float]]
function mapValues(map, loc, errors, check) {
  for (const [key, value] of Object.entries(map)) check(value, [...loc, key]);
  return clone(map);
}

const COLLECTION_CHECKS = {
  "filters.whitelist_names": stringList,
  "filters.blacklist_names": stringList,
  "filters.whitelist_labels": labelFilterList,
  "filters.blacklist_labels": labelFilterList,
  "containers.selected": stringList,
  "containers.excluded": stringList,
  "containers.restart_counts": (map, loc, errors) =>
    mapValues(map, loc, errors, (value, valueLoc) => {
      if (!Number.isInteger(value)) {
        errors.push({
          type: "int_type",
          loc: valueLoc,
          msg: "Input should be a valid integer",
        });
      }
    }),
  "containers.restart_history": (map, loc, errors) =>
    mapValues(map, loc, errors, (value, valueLoc) => {
      if (!Array.isArray(value)) {
        errors.push({
          type: "list_type",
          loc: valueLoc,
          msg: "Input should be a valid list",
        });
        return;
      }
      value.forEach((time, index) => {
        if (typeof time !== "number") {
          errors.push({
            type: "float_type",
            loc: [...valueLoc, index],
            msg: "Input should be a valid number",
          });
        }
      });
    }),
  "notifications.event_filters": stringList,
  "notifications.services": (items, loc, errors) =>
    items.map((service, index) =>
      validateNotificationService(service, [...loc, index], errors),
    ),
};

/**
 * Copy one section's known fields onto its defaults, like the Pydantic model:
 * unknown keys are dropped, and a value of the wrong kind (list, object,
 * string, number or boolean, judged by the default) is a 422, as is a bad
 * element of a typed collection. A null default is an optional string.
 */
function mergeSection(target, values, loc, errors) {
  const kind = (value) => (Array.isArray(value) ? "list" : typeof value);
  for (const [key, value] of Object.entries(values)) {
    // Own keys only: inherited names (toString, __proto__, ...) are unknown.
    if (!Object.hasOwn(target, key)) continue;
    const expected = target[key];
    if (expected === null) {
      if (value === null || isString(value)) target[key] = value;
      else checkKind(value, "string", [...loc, key], errors);
    } else if (kind(expected) === kind(value)) {
      const check = COLLECTION_CHECKS[`${loc.at(-1)}.${key}`];
      target[key] = check ? check(value, [...loc, key], errors) : clone(value);
    } else {
      errors.push({
        type: `${kind(expected)}_type`,
        loc: [...loc, key],
        msg: `Input should be a valid ${kind(expected)}`,
      });
    }
  }
}

// list[UptimeKumaMapping]
function mappingList(items, loc, errors) {
  return items.map((item, index) => {
    const itemLoc = [...loc, index];
    if (!isObject(item)) {
      errors.push({
        type: "model_type",
        loc: itemLoc,
        msg: "Input should be a valid dictionary",
      });
      return null;
    }
    for (const field of ["container_id", "monitor_friendly_name"]) {
      if (field in item) {
        checkKind(item[field], "string", [...itemLoc, field], errors);
      } else {
        errors.push({
          type: "missing",
          loc: [...itemLoc, field],
          msg: "Field required",
        });
      }
    }
    if ("auto_mapped" in item) {
      checkKind(
        item.auto_mapped,
        "boolean",
        [...itemLoc, "auto_mapped"],
        errors,
      );
    }
    return {
      container_id: item.container_id,
      monitor_friendly_name: item.monitor_friendly_name,
      auto_mapped: item.auto_mapped ?? false,
    };
  });
}

/** AutoHealConfig(**data): unknown keys dropped, missing sections defaulted. */
function validateFullConfig(data, loc = ["body"]) {
  if (!isObject(data)) {
    throw new ApiError(422, [
      { type: "model_type", loc, msg: "Input should be a valid dictionary" },
    ]);
  }
  const errors = [];
  const config = clone(defaultConfig);
  for (const section of Object.keys(config)) {
    if (!(section in data)) continue;
    if (section === "monitor") {
      config.monitor = validateMonitor(
        data.monitor,
        [...loc, "monitor"],
        errors,
      );
    } else if (section === "restart") {
      config.restart = validateRestart(
        data.restart,
        [...loc, "restart"],
        errors,
      );
    } else if (section === "uptime_kuma_mappings") {
      if (Array.isArray(data[section])) {
        config[section] = mappingList(data[section], [...loc, section], errors);
      } else {
        errors.push({
          type: "list_type",
          loc: [...loc, section],
          msg: "Input should be a valid list",
        });
      }
    } else if (isObject(data[section])) {
      mergeSection(config[section], data[section], [...loc, section], errors);
    } else {
      errors.push({
        type: "model_type",
        loc: [...loc, section],
        msg: "Input should be a valid dictionary",
      });
    }
  }
  raiseIfInvalid(errors);
  return config;
}

const OPTIONAL_SERVICE_FIELDS = [
  "url",
  "headers",
  "username",
  "password",
  "bot_token",
  "chat_id",
  "topic",
  "server_url",
  "access_token",
  "app_token",
  "user_key",
  "api_token",
];

/**
 * NotificationService(**service): the normalised service, or null after
 * pushing its errors (located under `loc`) onto `errors`.
 */
function validateNotificationService(service, loc, errors) {
  if (!isObject(service)) {
    errors.push({
      type: "model_type",
      loc,
      msg: "Input should be a valid dictionary",
    });
    return null;
  }
  const before = errors.length;
  for (const field of ["name", "type"]) {
    if (field in service) {
      checkKind(service[field], "string", [...loc, field], errors);
    } else {
      errors.push({
        type: "missing",
        loc: [...loc, field],
        msg: "Field required",
      });
    }
  }
  if ("enabled" in service) {
    checkKind(service.enabled, "boolean", [...loc, "enabled"], errors);
  }
  for (const field of OPTIONAL_SERVICE_FIELDS) {
    const value = service[field];
    if (value == null) continue;
    if (field === "headers") {
      if (!isObject(value)) {
        errors.push({
          type: "dict_type",
          loc: [...loc, field],
          msg: "Input should be a valid dictionary",
        });
      }
    } else {
      checkKind(value, "string", [...loc, field], errors);
    }
  }
  if (errors.length > before) return null;
  const result = {
    name: service.name,
    type: service.type,
    enabled: service.enabled ?? true,
  };
  for (const field of OPTIONAL_SERVICE_FIELDS) {
    result[field] = service[field] ?? null;
  }
  return result;
}

const CHECK_TYPE_FIELDS = {
  http: ["http_endpoint", "http_expected_status"],
  tcp: ["tcp_port"],
  exec: ["exec_command"],
  docker: [],
};

function validateHealthCheck(body) {
  const hc = {
    interval_seconds: 30,
    timeout_seconds: 10,
    retries: 3,
    http_endpoint: null,
    http_expected_status: 200,
    tcp_port: null,
    exec_command: null,
    ...(isObject(body) ? body : {}),
  };
  const fail = (msg) => {
    throw new ApiError(422, [
      { type: "value_error", loc: ["body"], msg: `Value error, ${msg}` },
    ]);
  };
  if (typeof hc.container_id !== "string") fail("container_id is required");
  const required = Object.hasOwn(CHECK_TYPE_FIELDS, hc.check_type)
    ? CHECK_TYPE_FIELDS[hc.check_type]
    : null;
  if (!required) {
    fail("Unknown check_type; expected one of: http, tcp, exec, docker");
  }
  const missing = required.filter((field) => hc[field] == null);
  if (missing.length)
    fail(`check_type '${hc.check_type}' requires: ${missing.join(", ")}`);
  if (hc.check_type === "http" && !String(hc.http_endpoint).trim()) {
    fail("http_endpoint must not be empty");
  }
  if (hc.check_type === "tcp" && !(hc.tcp_port >= 1 && hc.tcp_port <= 65535)) {
    fail("tcp_port must be between 1 and 65535");
  }
  if (
    hc.check_type === "exec" &&
    !(Array.isArray(hc.exec_command) && String(hc.exec_command[0] ?? "").trim())
  ) {
    fail(
      "exec_command must be a non-empty list starting with a non-blank command",
    );
  }
  return hc;
}

// --- route handlers --------------------------------------------------------

function requireContainer(engine, id) {
  const container = engine.findContainer(decodeURIComponent(id));
  if (!container) throw new ApiError(404, "Container not found");
  return container;
}

function containerInfoForList(engine, info) {
  const uptimeKumaEnabled = engine.config.uptime_kuma.enabled;
  return {
    id: info.id,
    name: info.name,
    image: info.image,
    status: info.status,
    state: info.state,
    labels: info.labels,
    health: info.health,
    restart_count: engine.totalRestartCount(info.recovery_id),
    monitored: engine.shouldMonitorInfo(info),
    quarantined: engine.quarantined.has(info.recovery_id),
    // 4 = enabled but no monitor (it can't connect in the demo), 5 = disabled
    uptime_kuma_status: uptimeKumaEnabled ? 4 : 5,
    uptime_kuma_monitor_name: null,
  };
}

function applySelection(containersConfig, cid, info, enabled) {
  const addTo = enabled ? containersConfig.selected : containersConfig.excluded;
  const removeFrom = enabled
    ? containersConfig.excluded
    : containersConfig.selected;
  const remove = (identifier) => {
    const index = removeFrom.indexOf(identifier);
    if (index !== -1) removeFrom.splice(index, 1);
  };
  if (!info) {
    if (!addTo.includes(cid)) addTo.push(cid);
    remove(cid);
    return;
  }
  if (!addTo.includes(info.stable_id)) addTo.push(info.stable_id);
  for (const identifier of [info.stable_id, info.name, cid]) remove(identifier);
}

function notificationsView(config) {
  return {
    enabled: config.notifications.enabled,
    services: clone(config.notifications.services),
    event_filters: [...config.notifications.event_filters],
  };
}

function findService(engine, name) {
  return engine.config.notifications.services.findIndex(
    (s) => s.name === decodeURIComponent(name),
  );
}

const DEMO_TEST_MESSAGE =
  "Demo: nothing was sent. In a real install this sends a test notification to the service.";

const routes = [
  [
    "get",
    /^\/health$/,
    (engine) => ({
      status: "healthy",
      timestamp: new Date(engine.clock()).toISOString(),
      docker_connected: true,
      monitoring_active: engine.running,
    }),
  ],

  [
    "get",
    /^\/api\/status$/,
    (engine) => {
      const infos = engine.containers.map((c) => engine.info(c));
      return {
        monitoring_active: engine.running,
        docker_connected: true,
        total_containers: infos.length,
        monitored_containers: infos.filter((i) => engine.shouldMonitorInfo(i))
          .length,
        quarantined_containers: engine.quarantined.size,
        maintenance_mode: engine.maintenanceMode,
        maintenance_start_time: engine.maintenanceStart,
        config: clone(engine.config),
      };
    },
  ],

  [
    "get",
    /^\/api\/containers$/,
    (engine, { params }) => {
      const includeStopped = String(params.include_stopped) === "true";
      return engine.containers
        .filter((c) => includeStopped || c.running)
        .map((c) => containerInfoForList(engine, engine.info(c)));
    },
  ],

  [
    "post",
    /^\/api\/containers\/select$/,
    (engine, { body }) => {
      if (
        !isObject(body) ||
        !Array.isArray(body.container_ids) ||
        typeof body.enabled !== "boolean"
      ) {
        throw new ApiError(422, [
          {
            type: "missing",
            loc: ["body"],
            msg: "container_ids (list) and enabled (bool) are required",
          },
        ]);
      }
      for (const cid of body.container_ids) {
        const container = engine.findContainer(cid);
        applySelection(
          engine.config.containers,
          cid,
          container ? engine.info(container) : null,
          body.enabled,
        );
      }
      return {
        status: "success",
        message: `Updated ${body.container_ids.length} containers`,
      };
    },
  ],

  [
    "get",
    /^\/api\/containers\/([^/]+)$/,
    (engine, { match }) => {
      const info = engine.info(requireContainer(engine, match[1]));
      const recoveryId = info.recovery_id;
      const total = engine.totalRestartCount(recoveryId);
      return {
        ...info,
        restart_count: total,
        monitored: engine.shouldMonitorInfo(info),
        quarantined: engine.quarantined.has(recoveryId),
        recent_restart_count: engine.restartCount(
          recoveryId,
          engine.config.restart.max_restarts_window_seconds,
        ),
        total_restart_count: total,
        custom_health_check:
          engine.customHealthChecks[info.stable_id] ??
          engine.customHealthChecks[info.name] ??
          engine.customHealthChecks[info.full_id] ??
          null,
      };
    },
  ],

  [
    "post",
    /^\/api\/containers\/([^/]+)\/restart$/,
    (engine, { match }) => {
      // Like the real route: a plain Docker restart, not counted as an Autoheal restart.
      engine._dockerRestart(requireContainer(engine, match[1]));
      return {
        status: "success",
        message: `Container ${decodeURIComponent(match[1])} restarted`,
      };
    },
  ],

  [
    "post",
    /^\/api\/containers\/([^/]+)\/unquarantine$/,
    (engine, { match }) => {
      const info = engine.info(requireContainer(engine, match[1]));
      engine.quarantined.delete(info.recovery_id);
      engine.clearRestartHistory(info.recovery_id);
      engine.addEvent({
        container_name: `${info.name} (${info.recovery_id})`,
        container_id: info.full_id,
        event_type: "unquarantine",
        restart_count: 0,
        status: "success",
        message: "Container un-quarantined by user request",
      });
      return {
        status: "success",
        message: `Container ${info.name} removed from quarantine`,
      };
    },
  ],

  [
    "post",
    /^\/api\/maintenance\/enable$/,
    (engine) => {
      engine.maintenanceMode = true;
      engine.maintenanceStart = new Date(engine.clock()).toISOString();
      return {
        status: "success",
        message: "Maintenance mode enabled",
        maintenance_mode: true,
        maintenance_start_time: engine.maintenanceStart,
      };
    },
  ],
  [
    "post",
    /^\/api\/maintenance\/disable$/,
    (engine) => {
      engine.maintenanceMode = false;
      engine.maintenanceStart = null;
      return {
        status: "success",
        message: "Maintenance mode disabled",
        maintenance_mode: false,
      };
    },
  ],
  [
    "get",
    /^\/api\/maintenance\/status$/,
    (engine) => ({
      maintenance_mode: engine.maintenanceMode,
      maintenance_start_time: engine.maintenanceStart,
    }),
  ],

  ["get", /^\/api\/config$/, (engine) => clone(engine.config)],
  [
    "put",
    /^\/api\/config$/,
    (engine, { body }) => {
      const config = validateFullConfig(body);
      // update_config keeps the live restart counts and history
      config.containers.restart_counts =
        engine.config.containers.restart_counts;
      config.containers.restart_history =
        engine.config.containers.restart_history;
      engine.config = config;
      return { status: "success", message: "Configuration updated" };
    },
  ],
  [
    "put",
    /^\/api\/config\/monitor$/,
    (engine, { body }) => {
      const errors = [];
      const monitor = validateMonitor(body, ["body"], errors);
      raiseIfInvalid(errors);
      engine.config.monitor = monitor;
      return { status: "success", message: "Monitor configuration updated" };
    },
  ],
  [
    "put",
    /^\/api\/config\/restart$/,
    (engine, { body }) => {
      const errors = [];
      const restart = validateRestart(body, ["body"], errors);
      raiseIfInvalid(errors);
      engine.config.restart = restart;
      return { status: "success", message: "Restart configuration updated" };
    },
  ],
  [
    "put",
    /^\/api\/config\/observability$/,
    (engine, { body }) => {
      requireObjectBody(body);
      const kinds = {
        log_level: "string",
        prometheus_enabled: "boolean",
        log_format: "string",
      };
      const errors = [];
      for (const [key, kind] of Object.entries(kinds)) {
        if (key in body) checkKind(body[key], kind, [key], errors);
      }
      raiseInvalidInput(errors);
      const observability = engine.config.observability;
      for (const key of Object.keys(kinds)) {
        if (key in body) observability[key] = body[key];
      }
      return {
        status: "success",
        message: "Observability configuration updated",
      };
    },
  ],
  [
    "get",
    /^\/api\/config\/export$/,
    (engine) => ({
      ...clone(engine.config),
      custom_health_checks: clone(engine.customHealthChecks),
    }),
  ],
  [
    "post",
    /^\/api\/config\/import$/,
    async (engine, { rawData }) => {
      const file =
        typeof rawData?.get === "function" ? rawData.get("file") : null;
      if (!file || typeof file.text !== "function") {
        throw new ApiError(422, [
          { type: "missing", loc: ["body", "file"], msg: "Field required" },
        ]);
      }
      // As import_config in app/api/routes/config.py: every bad file is a 422
      // with a fixed message, and nothing changes unless all of it is valid.
      let data;
      try {
        data = JSON.parse(await file.text());
      } catch {
        throw new ApiError(422, "File is not valid JSON");
      }
      if (!isObject(data)) {
        throw new ApiError(422, "Configuration must be a JSON object");
      }
      const customChecks = data.custom_health_checks ?? {};
      if (
        !isObject(customChecks) ||
        !Object.values(customChecks).every(isObject)
      ) {
        throw new ApiError(
          422,
          "custom_health_checks must be an object whose values are health check objects",
        );
      }
      delete data.custom_health_checks;
      const checks = {};
      let config;
      try {
        config = validateFullConfig(data, []);
        for (const [cid, hc] of Object.entries(customChecks)) {
          checks[cid] = validateHealthCheck(hc);
        }
      } catch (error) {
        // Both validators throw a 422 ApiError whose detail is a list.
        raiseInvalidInput(error.detail);
      }
      engine.config = config;
      engine.customHealthChecks = checks;
      return {
        status: "success",
        message: "Configuration imported successfully",
      };
    },
  ],

  [
    "get",
    /^\/api\/healthchecks$/,
    (engine) => clone(engine.customHealthChecks),
  ],
  [
    "post",
    /^\/api\/healthchecks$/,
    (engine, { body }) => {
      const hc = validateHealthCheck(body);
      const info = engine.info(requireContainer(engine, hc.container_id));
      hc.container_id = info.stable_id;
      engine.customHealthChecks[info.stable_id] = hc;
      return {
        status: "success",
        message: `Health check added for container ${info.stable_id}`,
      };
    },
  ],
  [
    "get",
    /^\/api\/healthchecks\/([^/]+)$/,
    (engine, { match }) => {
      const info = engine.info(requireContainer(engine, match[1]));
      const hc =
        engine.customHealthChecks[info.stable_id] ??
        engine.customHealthChecks[info.full_id];
      if (!hc)
        throw new ApiError(
          404,
          "No custom health check found for this container",
        );
      return clone(hc);
    },
  ],
  [
    "delete",
    /^\/api\/healthchecks\/([^/]+)$/,
    (engine, { match }) => {
      const info = engine.info(requireContainer(engine, match[1]));
      const key = engine.customHealthChecks[info.stable_id]
        ? info.stable_id
        : info.full_id;
      delete engine.customHealthChecks[key];
      return {
        status: "success",
        message: `Health check removed for container ${decodeURIComponent(match[1])}`,
      };
    },
  ],

  [
    "get",
    /^\/api\/events$/,
    (engine, { params }) => {
      const limit = params.limit === undefined ? 100 : Number(params.limit);
      if (!Number.isInteger(limit) || limit < 1) {
        throw new ApiError(422, [
          {
            type: "greater_than_equal",
            loc: ["query", "limit"],
            msg: "Input should be greater than or equal to 1",
          },
        ]);
      }
      let events = engine.events;
      if (params.event_type != null) {
        events = events.filter((e) => e.event_type === params.event_type);
      }
      if (params.container != null) {
        const needle = String(params.container).toLowerCase();
        events = events.filter((e) =>
          e.container_name.toLowerCase().includes(needle),
        );
      }
      return clone(events.slice(-limit));
    },
  ],
  [
    "delete",
    /^\/api\/events$/,
    (engine) => {
      engine.events = [];
      return { status: "success", message: "All events cleared" };
    },
  ],

  [
    "get",
    /^\/api\/notifications\/config$/,
    (engine) => notificationsView(engine.config),
  ],
  [
    "put",
    /^\/api\/notifications\/config$/,
    (engine, { body }) => {
      requireObjectBody(body);
      const notifications = engine.config.notifications;
      // NotificationsConfig.model_validate of the merged section
      const errors = [];
      if ("enabled" in body) {
        checkKind(body.enabled, "boolean", ["enabled"], errors);
      }
      if ("event_filters" in body) {
        checkKind(body.event_filters, "list", ["event_filters"], errors);
        if (Array.isArray(body.event_filters)) {
          body.event_filters.forEach((filter, i) =>
            checkKind(filter, "string", ["event_filters", i], errors),
          );
        }
      }
      let services = notifications.services;
      if ("services" in body) {
        checkKind(body.services, "list", ["services"], errors);
        if (Array.isArray(body.services)) {
          services = body.services.map((service, i) =>
            validateNotificationService(service, ["services", i], errors),
          );
        }
      }
      raiseInvalidInput(errors);
      if ("enabled" in body) notifications.enabled = body.enabled;
      if ("event_filters" in body)
        notifications.event_filters = [...body.event_filters];
      notifications.services = services;
      return {
        status: "success",
        message: "Notification configuration updated",
        config: notificationsView(engine.config),
      };
    },
  ],
  [
    "post",
    /^\/api\/notifications\/services$/,
    (engine, { body }) => {
      requireObjectBody(body);
      const errors = [];
      const service = validateNotificationService(body, [], errors);
      raiseInvalidInput(errors);
      if (
        engine.config.notifications.services.some(
          (s) => s.name === service.name,
        )
      ) {
        throw new ApiError(
          400,
          `Service with name '${service.name}' already exists`,
        );
      }
      engine.config.notifications.services.push(service);
      return {
        status: "success",
        message: `Notification service '${service.name}' added`,
        service,
      };
    },
  ],
  [
    "put",
    /^\/api\/notifications\/services\/([^/]+)$/,
    (engine, { match, body }) => {
      requireObjectBody(body);
      const name = decodeURIComponent(match[1]);
      const index = findService(engine, match[1]);
      if (index === -1) throw new ApiError(404, `Service '${name}' not found`);
      // The name is kept when the body doesn't set one.
      const errors = [];
      const service = validateNotificationService(
        { name, ...body },
        [],
        errors,
      );
      raiseInvalidInput(errors);
      engine.config.notifications.services[index] = service;
      return {
        status: "success",
        message: `Notification service '${name}' updated`,
        service,
      };
    },
  ],
  [
    "delete",
    /^\/api\/notifications\/services\/([^/]+)$/,
    (engine, { match }) => {
      const name = decodeURIComponent(match[1]);
      const index = findService(engine, match[1]);
      if (index === -1) throw new ApiError(404, `Service '${name}' not found`);
      engine.config.notifications.services.splice(index, 1);
      return {
        status: "success",
        message: `Notification service '${name}' deleted`,
      };
    },
  ],
  [
    "post",
    /^\/api\/notifications\/test$/,
    (engine, { body }) => {
      if (!isObject(body))
        throw new ApiError(422, "Request body must be a JSON object");
      // This route reports field locations and messages only, as a list.
      const errors = [];
      validateNotificationService(body, [], errors);
      if (errors.length) {
        throw new ApiError(
          422,
          errors.map(({ loc, msg }) => ({ loc, msg })),
        );
      }
      return { status: "success", message: DEMO_TEST_MESSAGE };
    },
  ],
  [
    "post",
    /^\/api\/notifications\/test\/([^/]+)$/,
    (engine, { match }) => {
      const name = decodeURIComponent(match[1]);
      const index = findService(engine, match[1]);
      if (index === -1) throw new ApiError(400, `Service '${name}' not found`);
      if (!engine.config.notifications.services[index].enabled) {
        throw new ApiError(400, `Service '${name}' is disabled`);
      }
      return { status: "success", message: DEMO_TEST_MESSAGE };
    },
  ],

  // Uptime Kuma needs a real server, so the demo can only show the settings.
  [
    "post",
    /^\/api\/uptime-kuma\/test-connection$/,
    () => ({
      success: false,
      message: "Connection error: Uptime Kuma isn't available in the demo",
    }),
  ],
  [
    "post",
    /^\/api\/uptime-kuma\/enable$/,
    (engine, { body }) => {
      requireObjectBody(body);
      const ok = (v) => typeof v === "string" && v.trim();
      if (!ok(body.server_url) || !ok(body.api_token)) {
        throw new ApiError(400, "server_url and api_token are required");
      }
      const errors = [];
      if ("username" in body) {
        checkKind(body.username, "string", ["username"], errors);
      }
      if ("auto_restart_on_down" in body) {
        checkKind(
          body.auto_restart_on_down,
          "boolean",
          ["auto_restart_on_down"],
          errors,
        );
      }
      raiseInvalidInput(errors);
      // The real route now contacts the server; with none to reach, the
      // client error ends in the generic 500.
      throw new ApiError(500, INTERNAL_ERROR_DETAIL);
    },
  ],
  [
    "get",
    /^\/api\/uptime-kuma\/monitors$/,
    (engine) => {
      if (!engine.config.uptime_kuma.enabled) {
        throw new ApiError(400, "Uptime-Kuma integration not enabled");
      }
      return { monitors: [] };
    },
  ],
  [
    "get",
    /^\/api\/uptime-kuma\/mappings$/,
    (engine) => ({
      mappings: clone(engine.config.uptime_kuma_mappings),
    }),
  ],
  [
    "post",
    /^\/api\/uptime-kuma\/mappings$/,
    (engine, { body }) => {
      requireObjectBody(body);
      const filled = (v) => typeof v === "string" && v.trim();
      if (!filled(body.container_id) || !filled(body.monitor_friendly_name)) {
        throw new ApiError(
          400,
          "container_id and monitor_friendly_name are required",
        );
      }
      const container = engine.findContainer(body.container_id);
      if (!container) throw new ApiError(404, "Container not found");
      const mapping = {
        container_id: engine.info(container).stable_id,
        monitor_friendly_name: body.monitor_friendly_name,
        auto_mapped: false,
      };
      engine.config.uptime_kuma_mappings.push(mapping);
      return { success: true, mapping };
    },
  ],
  [
    "delete",
    /^\/api\/uptime-kuma\/mappings\/([^/]+)$/,
    (engine, { match }) => {
      const id = decodeURIComponent(match[1]);
      engine.config.uptime_kuma_mappings =
        engine.config.uptime_kuma_mappings.filter((m) => m.container_id !== id);
      return { success: true };
    },
  ],
  [
    "post",
    /^\/api\/uptime-kuma\/disable$/,
    (engine) => {
      engine.config.uptime_kuma.enabled = false;
      return { success: true };
    },
  ],
];

/** "a/b//" -> "a/b": a loop rather than /\/+$/, which backtracks. */
export function trimTrailingSlashes(text) {
  let end = text.length;
  while (end > 0 && text[end - 1] === "/") end--;
  return text.slice(0, end);
}

function requestPath(config) {
  let url = config.url ?? "";
  if (!/^[a-z]+:\/\//i.test(url) && config.baseURL) {
    url = `${trimTrailingSlashes(config.baseURL)}/${url.replace(/^\/+/, "")}`;
  }
  // Absolute URLs (or a VITE_API_URL with a host) keep only their path.
  url = url.replace(/^[a-z]+:\/\/[^/]+/i, "");
  const [path, query = ""] = url.split("?");
  return { path: trimTrailingSlashes(path) || "/", query };
}

function parseBody(data) {
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
}

/** Run one request against the engine: resolves to {status, data}. */
export async function handleRequest(engine, config) {
  const method = (config.method ?? "get").toLowerCase();
  const { path, query } = requestPath(config);
  const params = {
    ...Object.fromEntries(new URLSearchParams(query)),
    ...(config.params ?? {}),
  };
  const candidates = routes.filter(([, pattern]) => pattern.test(path));
  if (candidates.length === 0)
    return { status: 404, data: { detail: "Not Found" } };
  const route = candidates.find(([m]) => m === method);
  if (!route) return { status: 405, data: { detail: "Method Not Allowed" } };
  try {
    const data = await route[2](engine, {
      match: path.match(route[1]),
      params,
      body: parseBody(config.data),
      rawData: config.data,
    });
    return { status: 200, data };
  } catch (error) {
    if (error instanceof ApiError) {
      return { status: error.status, data: { detail: error.detail } };
    }
    // An unexpected error: the generic 500 (unhandled_exception_handler).
    console.error("Demo mock API error:", error);
    return { status: 500, data: { detail: INTERNAL_ERROR_DETAIL } };
  }
}

const STATUS_TEXT = {
  200: "OK",
  400: "Bad Request",
  404: "Not Found",
  405: "Method Not Allowed",
  422: "Unprocessable Entity",
  500: "Internal Server Error",
};

/** An axios adapter that answers every request from the demo engine. */
export function createMockAdapter(engine) {
  return async function demoAdapter(config) {
    const { status, data } = await handleRequest(engine, config);
    engine._emit();
    const response = {
      data,
      status,
      statusText: STATUS_TEXT[status],
      headers: { "content-type": "application/json" },
      config,
      request: {},
    };
    const validateStatus =
      config.validateStatus ?? ((s) => s >= 200 && s < 300);
    if (validateStatus(status)) return response;
    throw new AxiosError(
      `Request failed with status code ${status}`,
      status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
      config,
      response.request,
      response,
    );
  };
}
