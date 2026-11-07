// Demo-only simulation of the Autoheal backend, run entirely in the browser.
//
// Two halves:
// - a tiny fake Docker host (containers that run, crash, go unhealthy and
//   restart), driven by the visitor's scenario buttons;
// - a port of the real monitoring cycle that watches it. The monitoring part
//   mirrors app/monitor/monitoring_engine.py (_check_single_container,
//   _check_quarantined_container, _handle_container_restart), selection.py
//   and health.py, and uses RecoveryPolicy from ./recovery.js. When those
//   modules change, change this file in the same release.
//
// Nothing is persisted: every page load starts from the same seed state.

import defaultConfig from "./default-config.json";
import { RecoveryPolicy } from "./recovery.js";

// A crash-looping container stays up this long after each restart.
export const CRASH_AFTER_MS = 4000;
// Docker reports health "starting" this long after a (re)start.
export const HEALTH_STARTING_MS = 3000;
// How often the simulated Docker health check runs (for FailingStreak).
const HEALTHCHECK_INTERVAL_MS = 5000;
const DOCKER_ZERO_TIME = "0001-01-01T00:00:00Z";

// Shorter timings than the backend defaults so a visitor sees a full
// restart -> quarantine cycle in about a minute. They are ordinary config
// values (shown and editable on the Config page) and pass the UI's timing
// validation. "both" lets health-check failures and crashes trigger restarts.
export const DEMO_CONFIG_OVERRIDES = {
  monitor: { interval_seconds: 5 },
  restart: {
    mode: "both",
    cooldown_seconds: 10,
    max_restarts: 3,
    max_restarts_window_seconds: 300,
    backoff: { initial_seconds: 5, max_seconds: 60 },
  },
};

const clone = (value) => JSON.parse(JSON.stringify(value));

function demoConfig() {
  const config = clone(defaultConfig);
  Object.assign(config.monitor, DEMO_CONFIG_OVERRIDES.monitor);
  const { backoff, ...restart } = DEMO_CONFIG_OVERRIDES.restart;
  Object.assign(config.restart, restart);
  Object.assign(config.restart.backoff, backoff);
  return config;
}

function hexId(seed) {
  // Deterministic 64-character "Docker ID" so every visit looks the same.
  let hex = "";
  let x = seed * 2654435761;
  while (hex.length < 64) {
    x = (x * 1103515245 + 12345) % 2147483648;
    hex += x.toString(16).padStart(8, "0");
  }
  return hex.slice(0, 64);
}

function compose(service) {
  return {
    "com.docker.compose.project": "shop",
    "com.docker.compose.service": service,
    "com.docker.compose.container-number": "1",
  };
}

// The starting containers. `fault` is what is wrong with the app inside:
// null, "unhealthy" (health check fails until restarted) or "crashloop"
// (exits with code 1 a few seconds after every start).
export const SEED_CONTAINERS = [
  {
    name: "shop-web-1",
    image: "nginx:1.27-alpine",
    labels: { autoheal: "true", ...compose("web") },
    healthcheck: true,
    fault: null,
  },
  {
    name: "shop-api-1",
    image: "ghcr.io/example/shop-api:2.3.0",
    labels: { autoheal: "true", ...compose("api") },
    healthcheck: true,
    fault: "unhealthy",
  },
  {
    name: "shop-worker-1",
    image: "ghcr.io/example/shop-worker:2.3.0",
    labels: { autoheal: "true", ...compose("worker") },
    healthcheck: false,
    fault: "crashloop",
  },
  {
    name: "shop-db-1",
    image: "postgres:16-alpine",
    labels: { autoheal: "true", ...compose("db") },
    healthcheck: true,
    fault: null,
  },
  {
    name: "nightly-backup",
    image: "alpine:3.20",
    labels: { autoheal: "true" },
    healthcheck: false,
    fault: null,
    stoppedCleanly: true,
  },
  {
    name: "grafana",
    image: "grafana/grafana:11.3.0",
    labels: {},
    healthcheck: true,
    fault: null,
  },
];

// --- selection.py ---------------------------------------------------------

function fnmatch(name, pattern) {
  let regex = "";
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch === "*") regex += ".*";
    else if (ch === "?") regex += ".";
    else if (ch === "[") {
      const end = pattern.indexOf("]", i + 1);
      if (end === -1) regex += "\\[";
      else {
        let set = pattern.slice(i + 1, end);
        if (set.startsWith("!")) set = "^" + set.slice(1);
        regex += `[${set.replace(/\\/g, "\\\\")}]`;
        i = end;
      }
    } else regex += ch.replace(/[.+^${}()|\\]/g, "\\$&");
  }
  return new RegExp(`^${regex}$`, "s").test(name);
}

function listed(names, info, stableId) {
  const service = info.labels["com.docker.compose.service"];
  return (
    names.includes(stableId) ||
    names.includes(info.full_id) ||
    names.includes(info.id) ||
    names.includes(info.name) ||
    Boolean(service && names.includes(service))
  );
}

const matchesAnyLabel = (filters, labels) =>
  filters.some(
    (filter) =>
      Object.keys(filter).length > 0 &&
      Object.entries(filter).every(([k, v]) => labels[k] === v),
  );

export function shouldMonitor(config, info, stableId) {
  const { labels, name } = info;
  if (listed(config.containers.excluded, info, stableId)) return false;
  if (listed(config.containers.selected, info, stableId)) return true;

  const { monitor, filters } = config;
  const labelOk =
    monitor.include_all || labels[monitor.label_key] === monitor.label_value;
  if (!labelOk) return false;
  if (filters.blacklist_names.some((p) => fnmatch(name, p))) return false;
  if (matchesAnyLabel(filters.blacklist_labels, labels)) return false;
  const namesOk =
    filters.whitelist_names.length === 0 ||
    filters.whitelist_names.some((p) => fnmatch(name, p));
  const labelsOk =
    filters.whitelist_labels.length === 0 ||
    matchesAnyLabel(filters.whitelist_labels, labels);
  return namesOk && labelsOk;
}

// --- docker_client_wrapper.py identifiers ---------------------------------

export function stableIdentifier(labels, name) {
  if (labels["monitoring.id"]) return labels["monitoring.id"];
  const project = labels["com.docker.compose.project"];
  const service = labels["com.docker.compose.service"];
  if (project && service) return `${project}_${service}`;
  return name;
}

export function recoveryIdentifier(stableId, labels) {
  if (labels["monitoring.id"]) return `monitoring.id:${stableId}`;
  const project = labels["com.docker.compose.project"];
  const service = labels["com.docker.compose.service"];
  if (!(project && service)) return stableId;
  const number = labels["com.docker.compose.container-number"];
  if (typeof number === "string" && /^\d+$/.test(number)) {
    return `compose:${project}:${service}#${parseInt(number, 10)}`;
  }
  return stableId;
}

// --- the engine -----------------------------------------------------------

export class DemoEngine {
  /**
   * @param {object} [options]
   * @param {() => number} [options.clock] current time in ms
   */
  constructor({ clock = () => Date.now() } = {}) {
    this.clock = clock;
    this._timer = null;
    this._listeners = new Set();
    this.reset();
  }

  /** Put everything back to the seed state (keeps the loop running). */
  reset() {
    const now = this.clock();
    this.config = demoConfig();
    this.customHealthChecks = {};
    this.events = [];
    this.quarantined = new Set();
    this.maintenanceMode = false;
    this.maintenanceStart = null;
    this.recovery = new RecoveryPolicy(this.clock);
    this.containers = SEED_CONTAINERS.map((seed, index) => {
      // Stagger start times so the list doesn't look freshly booted.
      const startedAt = now - (3 + index) * 3600 * 1000;
      const container = {
        fullId: hexId(index + 1),
        name: seed.name,
        image: seed.image,
        imageId: `sha256:${hexId(index + 101)}`,
        labels: { ...seed.labels },
        created: new Date(startedAt - 60000).toISOString(),
        healthcheck: seed.healthcheck,
        fault: seed.fault,
        faultSince: startedAt,
        running: true,
        startedAt,
        finishedAt: null,
        exitCode: 0,
        dockerRestartCount: 0,
        failingStreak: 0,
        lastHealth: seed.healthcheck ? "healthy" : null,
      };
      if (seed.stoppedCleanly) {
        container.running = false;
        container.finishedAt = now - 2 * 3600 * 1000;
      }
      if (seed.fault === "crashloop") {
        // Crashed a moment ago, so the visitor sees Autoheal react at once.
        container.running = false;
        container.exitCode = 1;
        container.finishedAt = now - 1000;
      }
      return container;
    });
    this._sync();
    this._emit();
  }

  // --- lifecycle ---

  start() {
    if (this._timer !== null) return;
    const loop = () => {
      this.runCycle();
      this._timer = setTimeout(
        loop,
        this.config.monitor.interval_seconds * 1000,
      );
    };
    this._timer = setTimeout(loop, 0);
  }

  stop() {
    clearTimeout(this._timer);
    this._timer = null;
  }

  get running() {
    return this._timer !== null;
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  _emit() {
    for (const listener of this._listeners) listener();
  }

  // --- fake Docker host ---

  /** Advance container state to the current time (crashes, health). */
  _sync() {
    const now = this.clock();
    for (const c of this.containers) {
      if (
        c.running &&
        c.fault === "crashloop" &&
        now >= c.startedAt + CRASH_AFTER_MS
      ) {
        c.running = false;
        c.exitCode = 1;
        c.finishedAt = c.startedAt + CRASH_AFTER_MS;
      }
      if (c.healthcheck && c.running) {
        c.lastHealth = this._healthStatus(c, now);
        c.failingStreak =
          c.lastHealth === "unhealthy"
            ? 1 +
              Math.floor(
                (now -
                  Math.max(c.faultSince, c.startedAt + HEALTH_STARTING_MS)) /
                  HEALTHCHECK_INTERVAL_MS,
              )
            : 0;
      }
    }
  }

  _healthStatus(c, now) {
    if (now < c.startedAt + HEALTH_STARTING_MS) return "starting";
    return c.fault === "unhealthy" ? "unhealthy" : "healthy";
  }

  /** Docker-style restart: the container runs again with a new StartedAt. */
  _dockerRestart(c) {
    const now = this.clock();
    if (c.running) c.finishedAt = now;
    c.running = true;
    c.startedAt = now;
    c.exitCode = 0;
    c.dockerRestartCount += 1;
    c.failingStreak = 0;
    // A restart clears a transient fault; a crash loop survives it.
    if (c.fault === "unhealthy") c.fault = null;
    if (c.healthcheck) c.lastHealth = "starting";
    return true;
  }

  findContainer(idOrName) {
    this._sync();
    return (
      this.containers.find(
        (c) =>
          c.name === idOrName ||
          (idOrName.length >= 1 && c.fullId.startsWith(idOrName)),
      ) ?? null
    );
  }

  /** The dict DockerClientWrapper.get_container_info returns, as of now. */
  info(c) {
    this._sync();
    const stableId = stableIdentifier(c.labels, c.name);
    const startedAt = new Date(c.startedAt).toISOString();
    const finishedAt = c.finishedAt
      ? new Date(c.finishedAt).toISOString()
      : DOCKER_ZERO_TIME;
    let health = null;
    let stateHealth;
    if (c.healthcheck) {
      const log = {
        Start: new Date(this.clock() - 1000).toISOString(),
        End: new Date(this.clock() - 900).toISOString(),
        ExitCode: c.lastHealth === "unhealthy" ? 1 : 0,
        Output:
          c.lastHealth === "unhealthy"
            ? "curl: (22) The requested URL returned error: 503"
            : "OK",
      };
      health = {
        status: c.lastHealth,
        failing_streak: c.failingStreak,
        log,
      };
      stateHealth = {
        Status: c.lastHealth,
        FailingStreak: c.failingStreak,
        Log: [log],
      };
    }
    const status = c.running ? "running" : "exited";
    const state = {
      Status: status,
      Running: c.running,
      Paused: false,
      Restarting: false,
      OOMKilled: false,
      Dead: false,
      Pid: c.running ? 1000 + this.containers.indexOf(c) : 0,
      ExitCode: c.exitCode,
      Error: "",
      StartedAt: startedAt,
      FinishedAt: finishedAt,
      ...(stateHealth ? { Health: stateHealth } : {}),
    };
    return {
      id: c.fullId.slice(0, 12),
      full_id: c.fullId,
      name: c.name,
      stable_id: stableId,
      recovery_id: recoveryIdentifier(stableId, c.labels),
      image: c.image,
      image_id: c.imageId,
      status,
      state,
      labels: { ...c.labels },
      networks: ["shop_default"],
      created: c.created,
      started_at: startedAt,
      finished_at: finishedAt,
      exit_code: c.exitCode,
      restart_count: c.dockerRestartCount,
      health,
      restart_policy: { Name: "no", MaximumRetryCount: 0 },
      compose_project: c.labels["com.docker.compose.project"] ?? null,
      compose_service: c.labels["com.docker.compose.service"] ?? null,
    };
  }

  // --- config_manager.py state helpers ---

  shouldMonitorInfo(info) {
    return shouldMonitor(this.config, info, info.stable_id);
  }

  recordRestart(recoveryId) {
    const { restart_counts: counts, restart_history: history } =
      this.config.containers;
    counts[recoveryId] = (counts[recoveryId] ?? 0) + 1;
    const now = this.clock() / 1000;
    const window = this.config.restart.max_restarts_window_seconds;
    history[recoveryId] = (history[recoveryId] ?? []).filter(
      (t) => now - t < window,
    );
    history[recoveryId].push(now);
  }

  restartCount(recoveryId, windowSeconds) {
    const now = this.clock() / 1000;
    return (this.config.containers.restart_history[recoveryId] ?? []).filter(
      (t) => now - t < windowSeconds,
    ).length;
  }

  totalRestartCount(recoveryId) {
    return this.config.containers.restart_counts[recoveryId] ?? 0;
  }

  clearRestartHistory(recoveryId) {
    delete this.config.containers.restart_counts[recoveryId];
    delete this.config.containers.restart_history[recoveryId];
  }

  addEvent(event) {
    this.events.push({
      timestamp: new Date(this.clock()).toISOString(),
      ...event,
    });
    const max = this.config.ui.max_log_entries;
    if (this.events.length > max) this.events = this.events.slice(-max);
  }

  _event(info, recoveryId, fields) {
    this.addEvent({
      container_id: info.full_id,
      container_name: `${info.name} (${recoveryId})`,
      ...fields,
    });
  }

  // --- monitoring_engine.py ---

  /** One monitoring cycle (_check_containers). */
  runCycle() {
    this.recovery.beginCycle();
    this._sync();
    for (const c of this.containers) this._checkSingle(c);
    this._emit();
  }

  _checkSingle(c) {
    if (this.maintenanceMode) return;
    const config = this.config;
    const info = this.info(c);
    if (!this.shouldMonitorInfo(info)) {
      this.recovery.forgetContainer(info.full_id);
      return;
    }
    const recoveryId = info.recovery_id;
    const quarantineId = [recoveryId, info.name, info.full_id].find((id) =>
      this.quarantined.has(id),
    );
    if (quarantineId !== undefined) {
      this._checkQuarantined(c, info, quarantineId, recoveryId);
      return;
    }
    const [needsRestart, reason] = this.evaluateHealth(info);
    if (needsRestart) {
      this.recovery.noteUnhealthy(recoveryId);
      this._handleRestart(c, info, reason);
      return;
    }
    this.recovery.noteHealthy(
      recoveryId,
      info.full_id,
      info.state.Status === "running",
      config.restart,
    );
  }

  _checkQuarantined(c, info, quarantineId, recoveryId) {
    if (info.state.Status !== "running") return false;
    const [needsRestart] = this.evaluateHealth(info);
    if (
      needsRestart ||
      !this.recovery.quarantineRecoveryConfirmed(
        info.full_id,
        info,
        this.config.restart.mode,
        this.config.monitor.interval_seconds,
      )
    ) {
      return false;
    }
    this.quarantined.delete(quarantineId);
    this.clearRestartHistory(recoveryId);
    this.recovery.noteQuarantineReleased(
      info.full_id,
      recoveryId,
      () => this.config.restart.backoff.initial_seconds,
    );
    this._event(info, recoveryId, {
      event_type: "auto_unquarantine",
      restart_count: 0,
      status: "success",
      message:
        "Container automatically removed from quarantine - auto-healed and now healthy",
    });
    return true;
  }

  /** health.py HealthEvaluator.evaluate: [needsRestart, reason]. */
  evaluateHealth(info) {
    const { restart } = this.config;
    const status = info.state.Status.toLowerCase();
    if (["exited", "stopped", "dead"].includes(status)) {
      if (restart.mode === "on-failure" || restart.mode === "both") {
        const exitCode = info.state.ExitCode;
        if (exitCode === 0 && restart.respect_manual_stop) {
          return [false, "Manual stop (exit 0)"];
        }
        if (exitCode !== 0) {
          return [true, `Container exited with code ${exitCode}`];
        }
        return [true, "Container stopped (exit 0)"];
      }
    }
    if (restart.mode === "health" || restart.mode === "both") {
      const check = [info.stable_id, info.name, info.full_id]
        .map((key) => this.customHealthChecks[key])
        .find(Boolean);
      // Custom checks can't really probe anything here; they pass while the
      // simulated app is running and healthy, like a real probe would.
      if (
        check &&
        (status !== "running" || info.health?.status === "unhealthy")
      ) {
        return [true, `Custom health check failed (${check.check_type})`];
      }
      if (info.health?.status === "unhealthy") {
        return [true, "Docker health check reports unhealthy"];
      }
    }
    return [false, ""];
  }

  _handleRestart(c, info, reason) {
    // Notifications and alert webhooks are not sent in the demo.
    const { restart } = this.config;
    const recoveryId = info.recovery_id;

    if (
      this.recovery.secondsIntoCooldown(
        recoveryId,
        restart.cooldown_seconds,
      ) !== null
    ) {
      return;
    }
    const restartCount = this.restartCount(
      recoveryId,
      restart.max_restarts_window_seconds,
    );
    if (restartCount >= restart.max_restarts) {
      this.quarantined.add(recoveryId);
      this._event(info, recoveryId, {
        event_type: "quarantine",
        restart_count: restartCount,
        status: "quarantined",
        message: `Container quarantined: exceeded ${restart.max_restarts} restarts in ${restart.max_restarts_window_seconds}s window`,
      });
      return;
    }
    if (
      restart.backoff.enabled &&
      !this.recovery.restartWaitElapsed(recoveryId, info.full_id, restart)
    ) {
      return;
    }
    this.recovery.clearRestartWait(recoveryId);
    // A simulated restart always succeeds.
    this._dockerRestart(c);
    this.recordRestart(recoveryId);
    this.recovery.recordRestart(recoveryId);
    this._event(info, recoveryId, {
      event_type: "restart",
      restart_count: this.totalRestartCount(recoveryId),
      status: "success",
      message: `Restart successful: ${reason}`,
    });
  }

  // --- what the visitor can do to the fake Docker host ---

  /** Make the app's health check fail until the container is restarted. */
  failHealthCheck(name) {
    const c = this.findContainer(name);
    if (!c?.healthcheck || !c.running) return;
    c.fault = "unhealthy";
    c.faultSince = this.clock();
    this._sync();
    this._emit();
  }

  /** Kill the container: it exits with code 1 once. */
  crash(name) {
    const c = this.findContainer(name);
    if (!c?.running) return;
    c.running = false;
    c.exitCode = 1;
    c.finishedAt = this.clock();
    this._emit();
  }

  /** Make the app crash a few seconds after every start. */
  startCrashLoop(name) {
    const c = this.findContainer(name);
    if (!c) return;
    c.fault = "crashloop";
    if (c.running) this.crash(name);
    this._emit();
  }

  /** Fix the app: no more crashes or failing health checks. */
  fix(name) {
    const c = this.findContainer(name);
    if (!c) return;
    c.fault = null;
    if (c.running && c.healthcheck) this._sync();
    this._emit();
  }

  /** `docker stop`: a clean exit with code 0. */
  stopCleanly(name) {
    const c = this.findContainer(name);
    if (!c?.running) return;
    c.running = false;
    c.exitCode = 0;
    c.finishedAt = this.clock();
    this._emit();
  }

  /** What the scenario panel shows for each container. */
  describe() {
    this._sync();
    return this.containers.map((c) => {
      const info = this.info(c);
      return {
        name: c.name,
        running: c.running,
        healthcheck: c.healthcheck,
        fault: c.fault,
        monitored: this.shouldMonitorInfo(info),
        quarantined: this.quarantined.has(info.recovery_id),
      };
    });
  }
}
