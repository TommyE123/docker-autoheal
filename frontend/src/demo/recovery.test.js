import { describe, it, expect, beforeEach } from "vitest";
import {
  RecoveryPolicy,
  QUARANTINE_STABLE_CHECKS,
  uptimeSeconds,
} from "./recovery.js";

// Mirrors the behaviours app/tests/unit covers for app/monitor/recovery.py.
const T0 = Date.parse("2026-01-01T00:00:00Z");
const restart = {
  backoff: { initial_seconds: 10, multiplier: 2, max_seconds: 300 },
};
let now;
let policy;

beforeEach(() => {
  now = T0;
  policy = new RecoveryPolicy(() => now);
});

describe("default clock", () => {
  it("uses the current time", () => {
    const real = new RecoveryPolicy();
    real.recordRestart("r");
    expect(Math.abs(real.lastRestartTimes.get("r") - Date.now())).toBeLessThan(
      1000,
    );
  });
});

describe("uptimeSeconds", () => {
  it("handles real, invalid and zero StartedAt values", () => {
    expect(uptimeSeconds(new Date(T0 - 5000).toISOString(), T0)).toBe(5);
    expect(uptimeSeconds("not a date", T0)).toBeNull();
    expect(uptimeSeconds("0001-01-01T00:00:00Z", T0)).toBeNull();
  });
});

describe("restart backoff", () => {
  it("schedules a wait, then lets the restart go ahead and doubles the delay", () => {
    policy.beginCycle();
    expect(policy.restartWaitElapsed("r", "c1", restart)).toBe(false);
    expect(policy.restartWaitEnds("r")).toBe(T0 + 10000);
    now += 5000;
    policy.beginCycle();
    expect(policy.restartWaitElapsed("r", "c1", restart)).toBe(false);
    now += 5000;
    policy.beginCycle();
    expect(policy.restartWaitElapsed("r", "c1", restart)).toBe(true);
    expect(policy.backoffDelays.get("r")).toBe(20);
  });

  it("caps the delay at max_seconds", () => {
    policy.backoffDelays.set("r", 1000);
    policy.beginCycle();
    policy.restartWaitElapsed("r", "c1", restart);
    expect(policy.restartWaitEnds("r")).toBe(T0 + 300000);
  });

  it("starts a new wait when the last one was not confirmed in the previous cycle", () => {
    policy.beginCycle();
    policy.restartWaitElapsed("r", "c1", restart);
    policy.beginCycle();
    policy.beginCycle(); // a cycle without confirming the wait
    now += 20000;
    expect(policy.restartWaitElapsed("r", "c1", restart)).toBe(false);
    expect(policy.restartWaitEnds("r")).toBe(now + 10000);
  });

  it("lets another replica see a wait without confirming it", () => {
    policy.beginCycle();
    policy.restartWaitElapsed("r", "c1", restart);
    policy.beginCycle();
    expect(policy.restartWaitElapsed("r", "c2", restart)).toBe(false);
    expect(policy.restartWaitSeen.get("r")).toBe(1);
    expect(policy.restartWaitOwner.get("r")).toBe("c1");
  });

  it("only lets the container that started a wait cancel it", () => {
    policy.beginCycle();
    policy.restartWaitElapsed("r", "c1", restart);
    policy.cancelRestartWait("r", "c2");
    expect(policy.restartWaitEnds("r")).not.toBeNull();
    policy.noteHealthy("r", "c1", true, restart);
    expect(policy.restartWaitEnds("r")).toBeNull();
  });

  it("forgets a container's waits and healthy runs", () => {
    policy.beginCycle();
    policy.restartWaitElapsed("r", "c1", restart);
    policy.healthySince.set("r", ["c1", T0]);
    policy.healthySince.set("other", ["c2", T0]);
    policy.forgetContainer("c1");
    expect(policy.restartWaitEnds("r")).toBeNull();
    expect([...policy.healthySince.keys()]).toEqual(["other"]);
  });

  it("resets the backoff only after staying healthy for the current delay", () => {
    policy.backoffDelays.set("r", 20);
    policy.noteHealthy("r", "c1", true, restart);
    now += 10000;
    policy.noteHealthy("r", "c1", true, restart);
    expect(policy.backoffDelays.get("r")).toBe(20);
    now += 10000;
    policy.noteHealthy("r", "c1", true, restart);
    expect(policy.backoffDelays.get("r")).toBe(10);
    expect(policy.healthySince.has("r")).toBe(false);
  });

  it("restarts the healthy run for a new container or when not running", () => {
    policy.backoffDelays.set("r", 20);
    policy.noteHealthy("r", "c1", true, restart);
    now += 15000;
    policy.noteHealthy("r", "c2", true, restart);
    now += 10000;
    policy.noteHealthy("r", "c2", true, restart);
    expect(policy.backoffDelays.get("r")).toBe(20);
    policy.noteHealthy("r", "c2", false, restart);
    expect(policy.healthySince.has("r")).toBe(false);
    policy.healthySince.set("r", ["c2", now]);
    policy.noteUnhealthy("r");
    expect(policy.healthySince.has("r")).toBe(false);
  });
});

describe("cooldown", () => {
  it("reports seconds into the cooldown until it runs out", () => {
    expect(policy.secondsIntoCooldown("r", 60)).toBeNull();
    policy.recordRestart("r");
    now += 30000;
    expect(policy.secondsIntoCooldown("r", 60)).toBe(30);
    now += 30000;
    expect(policy.secondsIntoCooldown("r", 60)).toBeNull();
  });
});

describe("quarantine release", () => {
  const info = (startedAt, health = null) => ({
    started_at: startedAt,
    state: {},
    health,
  });

  it(`needs ${QUARANTINE_STABLE_CHECKS} consecutive healthy checks and enough uptime`, () => {
    const started = new Date(T0).toISOString();
    for (let check = 1; check <= QUARANTINE_STABLE_CHECKS; check++) {
      policy.beginCycle();
      const released = policy.quarantineRecoveryConfirmed(
        "c1",
        info(started),
        "both",
        5,
      );
      expect(released).toBe(check === QUARANTINE_STABLE_CHECKS);
      now += 8000; // third check at 16s uptime, over the 3 x 5s floor
    }
  });

  it("waits for the uptime floor even after enough checks", () => {
    const started = new Date(T0).toISOString();
    for (let check = 1; check <= 4; check++) {
      policy.beginCycle();
      expect(
        policy.quarantineRecoveryConfirmed("c1", info(started), "both", 30),
      ).toBe(false);
      now += 1000;
    }
  });

  it("breaks the streak on a skipped cycle or a new run", () => {
    const started = new Date(T0).toISOString();
    policy.beginCycle();
    policy.quarantineRecoveryConfirmed("c1", info(started), "both", 1);
    policy.beginCycle();
    policy.beginCycle();
    expect(policy.quarantineStreaks.has("c1")).toBe(false);
    policy.quarantineRecoveryConfirmed("c1", info(started), "both", 1);
    const restarted = new Date(T0 + 1).toISOString();
    policy.quarantineRecoveryConfirmed("c1", info(restarted), "both", 1);
    expect(policy.quarantineStreaks.get("c1")[1]).toBe(1);
  });

  it("does not count health 'starting' in the health modes, or a missing StartedAt", () => {
    const started = new Date(T0).toISOString();
    expect(
      policy.quarantineRecoveryConfirmed(
        "c1",
        info(started, { status: "starting" }),
        "health",
        1,
      ),
    ).toBe(false);
    expect(policy.quarantineStreaks.has("c1")).toBe(false);
    policy.quarantineRecoveryConfirmed(
      "c1",
      info(started, { status: "starting" }),
      "on-failure",
      1,
    );
    expect(policy.quarantineStreaks.has("c1")).toBe(true);
    expect(
      policy.quarantineRecoveryConfirmed("c2", { state: {} }, "both", 1),
    ).toBe(false);
    expect(
      policy.quarantineRecoveryConfirmed(
        "c3",
        { state: { StartedAt: started } },
        "both",
        1,
      ),
    ).toBe(false);
    expect(policy.quarantineStreaks.has("c3")).toBe(true);
  });

  it("resets a recorded backoff on release and keeps another replica's wait", () => {
    policy.beginCycle();
    policy.restartWaitElapsed("r", "other", restart);
    policy.backoffDelays.set("r", 40);
    policy.quarantineStreaks.set("c1", ["x", 3, 1]);
    policy.noteQuarantineReleased("c1", "r", () => 10);
    expect(policy.backoffDelays.get("r")).toBe(10);
    expect(policy.restartWaitEnds("r")).not.toBeNull();
    expect(policy.quarantineStreaks.has("c1")).toBe(false);
    policy.noteQuarantineReleased("c1", "none", () => 10);
    expect(policy.backoffDelays.has("none")).toBe(false);
  });

  it("counts cycles", () => {
    policy.beginCycle();
    policy.beginCycle();
    expect(policy.checkCycle).toBe(2);
  });
});
