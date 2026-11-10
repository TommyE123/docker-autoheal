// Checks the demo against the real backend's answers, stored in contract/ by
// app/tests/unit/test_demo_contract.py (which fails when the backend changes
// until they are refreshed). See docs/developer/demo.md.
import { describe, it, expect } from "vitest";
import apiContract from "./contract/api.json";
import validationContract from "./contract/validation.json";
import scenarioContract from "./contract/scenarios.json";
import defaultConfig from "./default-config.json";
import { DemoEngine } from "./engine.js";
import {
  ApiError,
  handleRequest,
  validateFullConfig,
  validateHealthCheck,
  validateNotificationService,
} from "./mockApi.js";

const clone = (value) => JSON.parse(JSON.stringify(value));

describe("API contract", () => {
  const samples = { container_id: "shop-web-1", service_name: "missing" };
  const routes = Object.entries(apiContract.routes).flatMap(([path, methods]) =>
    methods.map((method) => [method, path]),
  );

  it.each(routes)("the mock answers %s %s", async (method, path) => {
    const url = path.replace(/\{(\w+)\}/g, (_, name) => samples[name]);
    const { status, data } = await handleRequest(new DemoEngine(), {
      method,
      url,
    });
    // Any answer but "no such route": a missing body may well be a 422, and
    // a route may answer 404 with its own detail, e.g. "Container not found".
    expect(data).not.toEqual({ detail: "Not Found" });
    expect(status).not.toBe(405);
  });

  it("returns every field of the response models", async () => {
    const engine = new DemoEngine();
    const status = (await handleRequest(engine, { url: "/api/status" })).data;
    const containers = (await handleRequest(engine, { url: "/api/containers" }))
      .data;
    expect(Object.keys(status).sort()).toEqual(
      [...apiContract.models.SystemStatus].sort(),
    );
    for (const container of containers) {
      expect(Object.keys(container).sort()).toEqual(
        [...apiContract.models.ContainerInfo].sort(),
      );
    }
  });
});

/** The demo's answer for one stored case, in the stored shape. */
function demoValidate(model, input) {
  if (model === "NotificationService") {
    const errors = [];
    const value = validateNotificationService(clone(input), [], errors);
    return errors.length ? { errors } : { value };
  }
  try {
    const value =
      model === "AutoHealConfig"
        ? validateFullConfig(clone(input), [])
        : validateHealthCheck(clone(input));
    return { value };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    // The health check route reports FastAPI locations under "body".
    return {
      errors: error.detail.map(({ type, loc, msg }) => ({
        type,
        loc: loc.filter((part) => part !== "body"),
        msg,
      })),
    };
  }
}

describe("validation contract", () => {
  it.each(validationContract.cases.map((c) => [c.model, c]))(
    "%s %j",
    (model, { input, expected }) => {
      expect(demoValidate(model, input)).toEqual(expected);
    },
  );
});

function deepMerge(base, override) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const both =
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value) &&
      typeof merged[key] === "object" &&
      merged[key] !== null;
    merged[key] = both ? deepMerge(merged[key], value) : value;
  }
  return merged;
}

const T0 = Date.parse("2026-01-01T00:00:00Z");
const CONTAINER_ID = "c".repeat(64);
const iso = (seconds) =>
  new Date(T0 + seconds * 1000).toISOString().replace(".000Z", "Z");

/** Run the stored timeline through the demo engine, as the Python test does. */
function runScenario(scenario) {
  let now = T0;
  const engine = new DemoEngine({ clock: () => now });
  engine.config = deepMerge(clone(defaultConfig), scenario.config);
  const container = engine.containers[0];
  engine.containers = [container];
  let step;
  let restarted;
  // Feed the observed state in directly instead of the simulated Docker host.
  engine._sync = () => {};
  engine._dockerRestart = () => {
    restarted = true;
    return true;
  };
  engine.info = () => ({
    id: CONTAINER_ID.slice(0, 12),
    full_id: CONTAINER_ID,
    name: "worker",
    stable_id: "worker",
    recovery_id: "worker",
    status: step.status,
    state: {
      Status: step.status,
      ExitCode: step.exit_code,
      StartedAt: iso(step.started_at),
    },
    labels: scenario.labels,
    started_at: iso(step.started_at),
    exit_code: step.exit_code,
    health: step.health ? { status: step.health } : null,
  });

  return scenario.steps.map((current) => {
    step = current;
    now = T0 + step.at * 1000;
    restarted = false;
    const seen = engine.events.length;
    engine.runCycle();
    return {
      restarted,
      events: engine.events
        .slice(seen)
        .map(({ event_type, restart_count, status, message }) => ({
          event_type,
          restart_count,
          status,
          message,
        })),
      quarantined: engine.quarantined.has("worker"),
    };
  });
}

describe("scenario contract", () => {
  it.each(scenarioContract.scenarios.map((s) => [s.name, s]))(
    "%s",
    (name, scenario) => {
      expect(runScenario(scenario)).toEqual(scenario.expected);
    },
  );
});
