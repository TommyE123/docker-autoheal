// Demo-only port of app/monitor/recovery.py (RecoveryPolicy).
//
// The demo must not teach behaviour the real service doesn't have, so this
// mirrors the Python class method for method. Times are milliseconds since the
// epoch instead of datetimes; delays and config values stay in seconds. When
// recovery.py changes, change this file in the same release.

// Consecutive healthy checks, on the same container run, before a quarantined
// container is released (QUARANTINE_STABLE_CHECKS in recovery.py).
export const QUARANTINE_STABLE_CHECKS = 3;

/** Seconds from a Docker StartedAt timestamp to `now`, or null if unusable. */
export function uptimeSeconds(startedAt, now) {
  const started = Date.parse(startedAt);
  if (Number.isNaN(started) || new Date(started).getUTCFullYear() <= 1) {
    return null;
  }
  return (now - started) / 1000;
}

export class RecoveryPolicy {
  constructor(clock = () => Date.now()) {
    this._clock = clock;
    this.lastRestartTimes = new Map();
    this.backoffDelays = new Map();
    // recoveryId -> [containerId, healthySince]
    this.healthySince = new Map();
    this.nextAllowedRestart = new Map();
    this.restartWaitOwner = new Map();
    this.restartWaitSeen = new Map();
    this._checkCycle = 0;
    // containerId -> [startedAt, count, cycle]
    this.quarantineStreaks = new Map();
  }

  get checkCycle() {
    return this._checkCycle;
  }

  beginCycle() {
    this._checkCycle += 1;
    for (const [containerId, [, , cycle]] of this.quarantineStreaks) {
      if (cycle < this._checkCycle - 1) {
        this.quarantineStreaks.delete(containerId);
      }
    }
  }

  forgetContainer(containerId) {
    for (const [recoveryId, owner] of this.restartWaitOwner) {
      if (owner === containerId) this.clearRestartWait(recoveryId);
    }
    for (const [recoveryId, [owner]] of this.healthySince) {
      if (owner === containerId) this.healthySince.delete(recoveryId);
    }
  }

  noteUnhealthy(recoveryId) {
    this.healthySince.delete(recoveryId);
  }

  noteHealthy(recoveryId, containerId, running, restart) {
    this.cancelRestartWait(recoveryId, containerId);
    this._resetBackoffIfStable(recoveryId, containerId, running, restart);
  }

  _resetBackoffIfStable(recoveryId, containerId, running, restart) {
    if (!running) {
      this.healthySince.delete(recoveryId);
      return;
    }
    const now = this._clock();
    let [owner, healthySince] = this.healthySince.get(recoveryId) ?? [
      null,
      now,
    ];
    if (owner !== containerId) healthySince = now;
    this.healthySince.set(recoveryId, [containerId, healthySince]);
    const delay = this.backoffDelays.get(recoveryId);
    if (delay === undefined || (now - healthySince) / 1000 < delay) return;
    this.backoffDelays.set(recoveryId, restart.backoff.initial_seconds);
    this.healthySince.delete(recoveryId);
  }

  /** Seconds since the last restart while still in cooldown, else null. */
  secondsIntoCooldown(recoveryId, cooldownSeconds) {
    const lastRestart = this.lastRestartTimes.get(recoveryId);
    if (lastRestart !== undefined) {
      const elapsed = (this._clock() - lastRestart) / 1000;
      if (elapsed < cooldownSeconds) return elapsed;
    }
    return null;
  }

  /** True if the restart may go ahead now; otherwise schedules or waits. */
  restartWaitElapsed(recoveryId, containerId, restart) {
    const now = this._clock();
    let nextAllowed = this.nextAllowedRestart.get(recoveryId);
    if (nextAllowed !== undefined) {
      if (this.restartWaitSeen.get(recoveryId) < this._checkCycle - 1) {
        this.clearRestartWait(recoveryId);
        nextAllowed = undefined;
      } else if (this.restartWaitOwner.get(recoveryId) === containerId) {
        this.restartWaitSeen.set(recoveryId, this._checkCycle);
      }
    }
    const backoffDelay = Math.min(
      this.backoffDelays.get(recoveryId) ?? restart.backoff.initial_seconds,
      restart.backoff.max_seconds,
    );
    if (nextAllowed === undefined) {
      this.nextAllowedRestart.set(recoveryId, now + backoffDelay * 1000);
      this.restartWaitOwner.set(recoveryId, containerId);
      this.restartWaitSeen.set(recoveryId, this._checkCycle);
      return false;
    }
    if (now < nextAllowed) return false;

    this.backoffDelays.set(
      recoveryId,
      Math.min(
        Math.trunc(backoffDelay * restart.backoff.multiplier),
        restart.backoff.max_seconds,
      ),
    );
    return true;
  }

  /** When the pending backoff wait for a recovery ID ends, or null. */
  restartWaitEnds(recoveryId) {
    return this.nextAllowedRestart.get(recoveryId) ?? null;
  }

  cancelRestartWait(recoveryId, containerId) {
    if (this.restartWaitOwner.get(recoveryId) === containerId) {
      this.clearRestartWait(recoveryId);
    }
  }

  clearRestartWait(recoveryId) {
    this.nextAllowedRestart.delete(recoveryId);
    this.restartWaitOwner.delete(recoveryId);
    this.restartWaitSeen.delete(recoveryId);
  }

  recordRestart(recoveryId) {
    this.lastRestartTimes.set(recoveryId, this._clock());
  }

  quarantineRecoveryConfirmed(containerId, info, restartMode, intervalSeconds) {
    const health = info.health;
    if (
      (restartMode === "health" || restartMode === "both") &&
      health &&
      health.status === "starting"
    ) {
      return false;
    }
    const startedAt = info.started_at || info.state?.StartedAt || "";
    const uptime = uptimeSeconds(startedAt, this._clock());
    if (uptime === null) return false;

    const previous = this.quarantineStreaks.get(containerId);
    const count = previous && previous[0] === startedAt ? previous[1] + 1 : 1;
    this.quarantineStreaks.set(containerId, [
      startedAt,
      count,
      this._checkCycle,
    ]);
    return (
      count >= QUARANTINE_STABLE_CHECKS &&
      uptime >= QUARANTINE_STABLE_CHECKS * intervalSeconds
    );
  }

  noteQuarantineReleased(containerId, recoveryId, initialBackoff) {
    this.quarantineStreaks.delete(containerId);
    this.cancelRestartWait(recoveryId, containerId);
    if (this.backoffDelays.has(recoveryId)) {
      this.backoffDelays.set(recoveryId, initialBackoff());
    }
  }
}
