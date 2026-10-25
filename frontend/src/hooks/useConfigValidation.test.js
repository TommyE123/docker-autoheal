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
  it.each([
    [2, "Very short monitoring interval"],
    [600, "Very long monitoring interval"],
  ])(
    "warns about a monitoring interval of %ss",
    (intervalSeconds, expectedMessage) => {
      const config = {
        ...baseConfig,
        monitor: { interval_seconds: intervalSeconds },
      };
      const { validateTimingConfiguration } = useConfigValidation(config);

      const result = validateTimingConfiguration();

      expect(result.isValid).toBe(false);
      expect(result.errors.some((e) => e.includes(expectedMessage))).toBe(true);
      expect(result.suggestions.length).toBeGreaterThan(0);
    },
  );

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

  it("applies the backoff cap when estimating the time for repeated restarts", () => {
    const backoff = { enabled: true, initial_seconds: 30, multiplier: 3 };
    const restart = {
      cooldown_seconds: 5,
      max_restarts: 5,
      max_restarts_window_seconds: 300,
    };
    const uncapped = useConfigValidation({
      monitor: { interval_seconds: 5 },
      restart: { ...restart, backoff },
    }).validateTimingConfiguration();
    const capped = useConfigValidation({
      monitor: { interval_seconds: 5 },
      restart: { ...restart, backoff: { ...backoff, max_seconds: 30 } },
    }).validateTimingConfiguration();

    expect(uncapped.isValid).toBe(false);
    expect(capped.isValid).toBe(true);
  });

  it("caps the first backoff delay when the initial delay exceeds the cap", () => {
    const config = {
      monitor: { interval_seconds: 5 },
      restart: {
        cooldown_seconds: 5,
        max_restarts: 5,
        max_restarts_window_seconds: 300,
        backoff: {
          enabled: true,
          initial_seconds: 300,
          multiplier: 3,
          max_seconds: 30,
        },
      },
    };
    const { validateTimingConfiguration } = useConfigValidation(config);

    const result = validateTimingConfiguration();

    expect(result.isValid).toBe(true);
  });
});
