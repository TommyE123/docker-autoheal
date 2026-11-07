import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  DemoEngine,
  DEMO_CONFIG_OVERRIDES,
  CRASH_AFTER_MS,
  HEALTH_STARTING_MS,
  shouldMonitor,
  stableIdentifier,
  recoveryIdentifier,
} from "./engine.js";
import defaultConfig from "./default-config.json";

const T0 = Date.parse("2026-01-01T12:00:00Z");
let now;
let engine;

const seconds = () => (now - T0) / 1000;
const byName = (name) => engine.containers.find((c) => c.name === name);
const infoOf = (name) => engine.info(byName(name));
const eventsFor = (service) =>
  engine.events
    .filter((e) => e.container_name.includes(service))
    .map((e) => [e.event_type, (Date.parse(e.timestamp) - T0) / 1000]);

/** Run monitoring cycles every `interval` seconds until `until` seconds. */
function runUntil(until, interval = engine.config.monitor.interval_seconds) {
  while (seconds() <= until) {
    engine.runCycle();
    now += interval * 1000;
  }
}

beforeEach(() => {
  now = T0;
  engine = new DemoEngine({ clock: () => now });
});

describe("seed state", () => {
  it("uses the backend defaults with the demo's shorter timings", () => {
    expect(engine.config.monitor.interval_seconds).toBe(5);
    expect(engine.config.restart).toMatchObject({
      mode: "both",
      cooldown_seconds: 10,
      max_restarts: 3,
      max_restarts_window_seconds: 300,
      backoff: {
        enabled: true,
        initial_seconds: 5,
        multiplier: 2,
        max_seconds: 60,
      },
      respect_manual_stop: true,
    });
    expect(engine.config.ui).toEqual(defaultConfig.ui);
    expect(DEMO_CONFIG_OVERRIDES.monitor.interval_seconds).toBe(5);
  });

  it("starts with one healthy, one unhealthy, one crash-looping and one cleanly stopped container", () => {
    expect(infoOf("shop-web-1").health.status).toBe("healthy");
    expect(infoOf("shop-api-1").health.status).toBe("unhealthy");
    expect(infoOf("shop-worker-1")).toMatchObject({
      status: "exited",
      exit_code: 1,
    });
    expect(infoOf("nightly-backup")).toMatchObject({
      status: "exited",
      exit_code: 0,
    });
    expect(engine.describe().find((c) => c.name === "grafana").monitored).toBe(
      false,
    );
  });

  it("builds the container info dict get_container_info returns", () => {
    const info = infoOf("shop-web-1");
    expect(Object.keys(info).sort()).toEqual(
      [
        "id",
        "full_id",
        "name",
        "stable_id",
        "recovery_id",
        "image",
        "image_id",
        "status",
        "state",
        "labels",
        "networks",
        "created",
        "started_at",
        "finished_at",
        "exit_code",
        "restart_count",
        "health",
        "restart_policy",
        "compose_project",
        "compose_service",
      ].sort(),
    );
    expect(info.id).toBe(info.full_id.slice(0, 12));
    expect(info.full_id).toMatch(/^[0-9a-f]{64}$/);
    expect(info.stable_id).toBe("shop_web");
    expect(info.recovery_id).toBe("compose:shop:web#1");
    expect(info.state.Health.Status).toBe("healthy");
    expect(infoOf("nightly-backup").recovery_id).toBe("nightly-backup");
    expect(infoOf("nightly-backup").health).toBeNull();
    expect(infoOf("nightly-backup").state.Health).toBeUndefined();
  });
});

describe("identifiers", () => {
  it("matches docker_client_wrapper.py", () => {
    expect(stableIdentifier({ "monitoring.id": "x" }, "n")).toBe("x");
    expect(recoveryIdentifier("x", { "monitoring.id": "x" })).toBe(
      "monitoring.id:x",
    );
    const labels = {
      "com.docker.compose.project": "p",
      "com.docker.compose.service": "s",
    };
    expect(stableIdentifier(labels, "n")).toBe("p_s");
    expect(recoveryIdentifier("p_s", labels)).toBe("p_s");
    expect(
      recoveryIdentifier("p_s", {
        ...labels,
        "com.docker.compose.container-number": "02",
      }),
    ).toBe("compose:p:s#2");
    expect(
      recoveryIdentifier("p_s", {
        ...labels,
        "com.docker.compose.container-number": "x",
      }),
    ).toBe("p_s");
    expect(stableIdentifier({}, "n")).toBe("n");
  });
});

describe("crash loop -> restarts with cooldown and backoff -> quarantine", () => {
  it("follows the real timeline", () => {
    runUntil(70);
    // Wait 5s (initial backoff), restart; then 10s cooldown and a doubled backoff each time.
    expect(eventsFor("worker")).toEqual([
      ["restart", 5],
      ["restart", 25],
      ["restart", 55],
      ["quarantine", 65],
    ]);
    const quarantine = engine.events.at(-1);
    expect(quarantine).toMatchObject({
      container_name: "shop-worker-1 (compose:shop:worker#1)",
      container_id: byName("shop-worker-1").fullId,
      restart_count: 3,
      status: "quarantined",
      message: "Container quarantined: exceeded 3 restarts in 300s window",
    });
    const restart = engine.events.find((e) =>
      e.container_name.includes("worker"),
    );
    expect(restart).toMatchObject({
      restart_count: 1,
      status: "success",
      message: "Restart successful: Container exited with code 1",
    });
    expect(engine.quarantined.has("compose:shop:worker#1")).toBe(true);
  });

  it("leaves a quarantined container alone", () => {
    runUntil(70);
    const count = engine.events.length;
    runUntil(200);
    expect(
      engine.events.filter((e) => e.container_name.includes("worker")),
    ).toHaveLength(4);
    expect(engine.events.length).toBe(count);
    expect(infoOf("shop-worker-1").status).toBe("exited");
  });

  it("releases it after three healthy checks once fixed and restarted", () => {
    runUntil(70);
    engine.fix("shop-worker-1");
    now = T0 + 100 * 1000;
    engine._dockerRestart(byName("shop-worker-1"));
    runUntil(110);
    expect(engine.quarantined.size).toBe(1);
    runUntil(115);
    expect(engine.quarantined.size).toBe(0);
    expect(eventsFor("worker").at(-1)).toEqual(["auto_unquarantine", 115]);
    expect(engine.events.at(-1)).toMatchObject({
      restart_count: 0,
      status: "success",
      message:
        "Container automatically removed from quarantine - auto-healed and now healthy",
    });
    expect(engine.totalRestartCount("compose:shop:worker#1")).toBe(0);
    expect(engine.recovery.backoffDelays.get("compose:shop:worker#1")).toBe(5);
  });

  it("stays quarantined when restarted without fixing the app", () => {
    runUntil(70);
    now = T0 + 100 * 1000;
    engine._dockerRestart(byName("shop-worker-1"));
    runUntil(160);
    expect(engine.quarantined.size).toBe(1);
    expect(infoOf("shop-worker-1").status).toBe("exited");
  });
});

describe("health check failures", () => {
  it("restarts an unhealthy container, which then recovers and resets its backoff", () => {
    runUntil(5);
    expect(eventsFor("api")).toEqual([["restart", 5]]);
    expect(engine.events[0].message).toBe(
      "Restart successful: Docker health check reports unhealthy",
    );
    now = T0 + 6 * 1000;
    expect(infoOf("shop-api-1").health.status).toBe("starting");
    now = T0 + 5 * 1000 + HEALTH_STARTING_MS;
    expect(infoOf("shop-api-1").health.status).toBe("healthy");
    expect(engine.recovery.backoffDelays.get("compose:shop:api#1")).toBe(10);
    runUntil(30);
    expect(eventsFor("api")).toHaveLength(1);
    expect(engine.recovery.backoffDelays.get("compose:shop:api#1")).toBe(5);
  });

  it("counts the failing streak over time, not per request", () => {
    engine.failHealthCheck("shop-web-1");
    expect(infoOf("shop-web-1").health.failing_streak).toBe(1);
    engine.describe();
    engine.describe();
    expect(infoOf("shop-web-1").health.failing_streak).toBe(1);
    now += 10 * 1000;
    expect(infoOf("shop-web-1").health).toMatchObject({
      status: "unhealthy",
      failing_streak: 3,
    });
    expect(infoOf("shop-web-1").health.log.ExitCode).toBe(1);
  });

  it("ignores health in on-failure mode", () => {
    engine.config.restart.mode = "on-failure";
    runUntil(60);
    expect(eventsFor("api")).toEqual([]);
    expect(eventsFor("worker").length).toBeGreaterThan(0);
  });

  it("ignores exits in health mode", () => {
    engine.config.restart.mode = "health";
    runUntil(60);
    expect(eventsFor("worker")).toEqual([]);
    expect(eventsFor("api")).toEqual([["restart", 5]]);
  });

  it("fails a custom health check while the app is down", () => {
    engine.customHealthChecks.shop_db = { check_type: "http" };
    expect(engine.evaluateHealth(infoOf("shop-db-1"))).toEqual([false, ""]);
    engine.failHealthCheck("shop-db-1");
    expect(engine.evaluateHealth(infoOf("shop-db-1"))).toEqual([
      true,
      "Custom health check failed (http)",
    ]);
    engine.config.restart.mode = "health";
    engine.stopCleanly("shop-db-1");
    expect(engine.evaluateHealth(infoOf("shop-db-1"))[0]).toBe(true);
  });
});

describe("other decisions", () => {
  it("respects a clean stop unless respect_manual_stop is off", () => {
    runUntil(60);
    expect(eventsFor("nightly-backup")).toEqual([]);
    engine.config.restart.respect_manual_stop = false;
    runUntil(75);
    expect(eventsFor("nightly-backup")).toEqual([["restart", 70]]);
    expect(engine.events.at(-1).message).toBe(
      "Restart successful: Container stopped (exit 0)",
    );
  });

  it("restarts at once with backoff disabled", () => {
    engine.config.restart.backoff.enabled = false;
    runUntil(0);
    expect(eventsFor("worker")).toEqual([["restart", 0]]);
  });

  it("does nothing in maintenance mode", () => {
    engine.maintenanceMode = true;
    runUntil(60);
    expect(engine.events).toEqual([]);
  });

  it("ignores unmonitored containers until selected", () => {
    engine.crash("grafana");
    runUntil(20);
    expect(eventsFor("grafana")).toEqual([]);
    engine.config.containers.selected.push("grafana");
    runUntil(40);
    expect(eventsFor("grafana")).toEqual([["restart", 30]]);
  });

  it("caps the event log at ui.max_log_entries", () => {
    engine.config.ui.max_log_entries = 2;
    runUntil(70);
    expect(engine.events).toHaveLength(2);
    expect(engine.events.at(-1).event_type).toBe("quarantine");
  });

  it("prunes restart history outside the window", () => {
    engine.recordRestart("x");
    now += 400 * 1000;
    engine.recordRestart("x");
    expect(engine.config.containers.restart_history.x).toHaveLength(1);
    expect(engine.totalRestartCount("x")).toBe(2);
    expect(engine.restartCount("x", 300)).toBe(1);
  });
});

describe("visitor actions", () => {
  it("crash, crash loop, stop and fix change the simulated container", () => {
    engine.crash("shop-web-1");
    expect(infoOf("shop-web-1")).toMatchObject({
      status: "exited",
      exit_code: 1,
    });
    engine.crash("shop-web-1"); // already stopped: no-op
    engine._dockerRestart(byName("shop-web-1"));
    expect(infoOf("shop-web-1").restart_count).toBe(1);

    engine.startCrashLoop("shop-db-1");
    expect(infoOf("shop-db-1").status).toBe("exited");
    engine._dockerRestart(byName("shop-db-1"));
    now += CRASH_AFTER_MS;
    expect(infoOf("shop-db-1").status).toBe("exited");
    engine.fix("shop-db-1");
    engine._dockerRestart(byName("shop-db-1"));
    now += CRASH_AFTER_MS * 2;
    expect(infoOf("shop-db-1").status).toBe("running");

    engine.stopCleanly("shop-db-1");
    expect(infoOf("shop-db-1")).toMatchObject({
      status: "exited",
      exit_code: 0,
    });
    engine.stopCleanly("shop-db-1");
  });

  it("sets a crash loop on a stopped container without starting it", () => {
    engine.startCrashLoop("nightly-backup");
    expect(byName("nightly-backup")).toMatchObject({
      fault: "crashloop",
      running: false,
      exitCode: 0,
    });
  });

  it("only fails health checks of running containers that have one", () => {
    engine.failHealthCheck("nightly-backup");
    engine.failHealthCheck("shop-worker-1");
    engine.failHealthCheck("nope");
    engine.fix("nope");
    engine.startCrashLoop("nope");
    expect(byName("shop-worker-1").fault).toBe("crashloop");
    expect(byName("nightly-backup").fault).toBeNull();
  });

  it("restarting clears a failing health check but not a crash loop", () => {
    engine.failHealthCheck("shop-web-1");
    engine._dockerRestart(byName("shop-web-1"));
    expect(byName("shop-web-1").fault).toBeNull();
    engine._dockerRestart(byName("shop-worker-1"));
    expect(byName("shop-worker-1").fault).toBe("crashloop");
  });

  it("finds containers by name or ID prefix", () => {
    const web = byName("shop-web-1");
    expect(engine.findContainer("shop-web-1")).toBe(web);
    expect(engine.findContainer(web.fullId.slice(0, 12))).toBe(web);
    expect(engine.findContainer("missing")).toBeNull();
  });

  it("reset restores the seed state and notifies listeners", () => {
    const listener = vi.fn();
    const unsubscribe = engine.subscribe(listener);
    runUntil(70);
    engine.config.monitor.interval_seconds = 30;
    engine.reset();
    expect(engine.events).toEqual([]);
    expect(engine.quarantined.size).toBe(0);
    expect(engine.config.monitor.interval_seconds).toBe(5);
    expect(listener).toHaveBeenCalled();
    unsubscribe();
    listener.mockClear();
    engine.reset();
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("selection.py port", () => {
  const info = (name, labels = { autoheal: "true" }) => ({
    name,
    id: "abc",
    full_id: "abcdef",
    labels,
  });
  let config;
  beforeEach(() => {
    config = structuredClone(defaultConfig);
  });

  it("uses the label gate, excluded and selected lists", () => {
    expect(shouldMonitor(config, info("a"), "a")).toBe(true);
    expect(shouldMonitor(config, info("a", {}), "a")).toBe(false);
    config.monitor.include_all = true;
    expect(shouldMonitor(config, info("a", {}), "a")).toBe(true);
    config.containers.excluded.push("abc");
    expect(shouldMonitor(config, info("a"), "a")).toBe(false);
    config.containers.excluded = [];
    config.monitor.include_all = false;
    config.containers.selected.push("svc");
    expect(
      shouldMonitor(
        config,
        info("b", { "com.docker.compose.service": "svc" }),
        "b",
      ),
    ).toBe(true);
  });

  it("applies name and label filters with fnmatch patterns", () => {
    config.filters.blacklist_names = ["shop-*"];
    expect(shouldMonitor(config, info("shop-web-1"), "x")).toBe(false);
    expect(shouldMonitor(config, info("db"), "x")).toBe(true);
    config.filters.blacklist_names = [];
    config.filters.whitelist_names = ["db-?", "web[0-9]", "x[!a]", "a.b", "q["];
    expect(shouldMonitor(config, info("db-1"), "x")).toBe(true);
    expect(shouldMonitor(config, info("db-10"), "x")).toBe(false);
    expect(shouldMonitor(config, info("web7"), "x")).toBe(true);
    expect(shouldMonitor(config, info("xb"), "x")).toBe(true);
    expect(shouldMonitor(config, info("xa"), "x")).toBe(false);
    expect(shouldMonitor(config, info("axb"), "x")).toBe(false);
    expect(shouldMonitor(config, info("a.b"), "x")).toBe(true);
    expect(shouldMonitor(config, info("q["), "x")).toBe(true);
    config.filters.whitelist_names = [];
    config.filters.whitelist_labels = [{ tier: "web" }];
    expect(
      shouldMonitor(config, info("a", { autoheal: "true", tier: "web" }), "x"),
    ).toBe(true);
    expect(shouldMonitor(config, info("a"), "x")).toBe(false);
    config.filters.whitelist_labels = [];
    config.filters.blacklist_labels = [{}, { tier: "web" }];
    expect(
      shouldMonitor(config, info("a", { autoheal: "true", tier: "web" }), "x"),
    ).toBe(false);
    expect(shouldMonitor(config, info("a"), "x")).toBe(true);
  });
});

describe("monitoring loop", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("runs a cycle at once and then every interval until stopped", () => {
    const real = new DemoEngine();
    const runCycle = vi.spyOn(real, "runCycle");
    real.start();
    real.start(); // idempotent
    expect(real.running).toBe(true);
    vi.advanceTimersByTime(0);
    expect(runCycle).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5000);
    expect(runCycle).toHaveBeenCalledTimes(2);
    real.stop();
    expect(real.running).toBe(false);
    vi.advanceTimersByTime(20000);
    expect(runCycle).toHaveBeenCalledTimes(2);
  });
});
