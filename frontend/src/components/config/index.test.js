import { describe, it, expect } from "vitest";
import * as configComponents from "./index";

describe("config components barrel module", () => {
  it("re-exports every config component as a component function", () => {
    const expectedNames = [
      "MonitorSettings",
      "RestartPolicySettings",
      "ObservabilitySettings",
      "ConfigImportExport",
      "UptimeKumaIntegration",
      "UptimeKumaConnectionForm",
      "UptimeKumaMonitorsList",
      "UptimeKumaMappings",
      "ValidationModal",
      "DisableUptimeKumaModal",
      "DeleteMappingModal",
    ];

    for (const name of expectedNames) {
      expect(typeof configComponents[name]).toBe("function");
    }
  });
});
