import { describe, it, expect } from "vitest";
import { validateModel } from "./schema.js";

// Cases the JSON contract can't hold (JSON has no infinity). Expected values
// were checked against the real BackoffConfig.
describe("validateModel", () => {
  it("parses Python's infinity strings as floats", () => {
    const errors = [];
    expect(
      validateModel("BackoffConfig", { multiplier: " +Infinity " }, [], errors)
        .multiplier,
    ).toBe(Infinity);
    expect(
      validateModel("BackoffConfig", { multiplier: "inf" }, [], errors)
        .multiplier,
    ).toBe(Infinity);
    expect(errors).toEqual([]);
    validateModel("BackoffConfig", { multiplier: "-inf" }, [], errors);
    expect(errors).toEqual([
      {
        type: "greater_than_equal",
        loc: ["multiplier"],
        msg: "Input should be greater than or equal to 1",
      },
    ]);
  });
});
