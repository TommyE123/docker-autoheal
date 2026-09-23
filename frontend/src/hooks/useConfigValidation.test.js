import { describe, it, expect } from "vitest";
import { useConfigValidation } from "./useConfigValidation";

const baseConfig = {
  monitor: { interval_seconds: 30 },
  restart: {
    cooldown_seconds: 10,
    max_restarts: 3,
    max_restarts_window_seconds: 300,
    backoff: { enabled: false, initial_seconds: 5, multiplier: 2 },
  },
};

describe("useConfigValidation", () => {
  it("reports no errors for a well-formed configuration", () => {
    const { validateTimingConfiguration } = useConfigValidation(baseConfig);

    const result = validateTimingConfiguration();

    expect(result.isValid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("flags a restart window too small for the configured cooldown and restart count", () => {
    const config = {
      ...baseConfig,
      restart: { ...baseConfig.restart, max_restarts_window_seconds: 5 },
    };
    const { validateTimingConfiguration } = useConfigValidation(config);

    const result = validateTimingConfiguration();

    expect(result.isValid).toBe(false);
    expect(result.errors.some((e) => e.includes("too small"))).toBe(true);
    expect(result.suggestions.length).toBeGreaterThan(0);
  });

  it("warns when exponential backoff would exceed the restart window", () => {
    const config = {
      monitor: { interval_seconds: 5 },
      restart: {
        cooldown_seconds: 5,
        max_restarts: 5,
        max_restarts_window_seconds: 60,
        backoff: { enabled: true, initial_seconds: 30, multiplier: 3 },
      },
    };
    const { validateTimingConfiguration } = useConfigValidation(config);

    const result = validateTimingConfiguration();

    expect(result.isValid).toBe(false);
    expect(result.errors.some((e) => e.includes("prevent quarantine"))).toBe(
      true,
    );
  });
});
