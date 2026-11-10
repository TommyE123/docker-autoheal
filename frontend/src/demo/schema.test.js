import { describe, it, expect } from "vitest";
import schemas from "./contract/schemas.json";
import { SUPPORTED_KEYWORDS, validateModel } from "./schema.js";

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

  it("reports a nested non-object model as FastAPI does for a request body", () => {
    const errors = [];
    validateModel("RestartConfig", { backoff: [] }, ["body"], errors, {
      fastapiBody: true,
    });
    expect(errors).toEqual([
      {
        type: "model_attributes_type",
        loc: ["body", "backoff"],
        msg: "Input should be a valid dictionary or object to extract fields from",
      },
    ]);
  });
});

// schema.js ignores keywords it doesn't implement, so a refreshed
// contract/schemas.json that uses a new one (an enum, a maxLength, ...) must
// fail here rather than be silently accepted.
describe("contract/schemas.json", () => {
  const problems = [];
  const walk = (node, path) => {
    if (Array.isArray(node)) {
      node.forEach((item, index) => walk(item, `${path}[${index}]`));
      return;
    }
    if (typeof node !== "object" || node === null) return;
    for (const [key, value] of Object.entries(node)) {
      // The names under these are field or model names, not keywords.
      if (key === "properties" || key === "$defs") {
        for (const [name, child] of Object.entries(value)) {
          walk(child, `${path}.${key}.${name}`);
        }
        continue;
      }
      if (key === "default") continue;
      if (!SUPPORTED_KEYWORDS.has(key)) problems.push(`${path}: ${key}`);
      walk(value, `${path}.${key}`);
    }
    if (node.anyOf) {
      const others = node.anyOf.filter((branch) => branch.type !== "null");
      if (others.length !== 1 || others.length === node.anyOf.length) {
        problems.push(`${path}: anyOf is not Optional[X]`);
      }
    }
    if (
      node.type === "object" &&
      !node.properties &&
      !node.additionalProperties
    ) {
      problems.push(`${path}: object without additionalProperties`);
    }
  };
  walk(schemas, "schemas");

  it("uses only keywords schema.js implements", () => {
    expect(problems).toEqual([]);
  });
});
