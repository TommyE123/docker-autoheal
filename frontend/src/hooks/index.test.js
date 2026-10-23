import { describe, it, expect } from "vitest";
import * as hooks from "./index";

describe("hooks barrel module", () => {
  it("re-exports useAlert and useConfigValidation as callable hooks", () => {
    expect(typeof hooks.useAlert).toBe("function");
    expect(typeof hooks.useConfigValidation).toBe("function");
  });
});
