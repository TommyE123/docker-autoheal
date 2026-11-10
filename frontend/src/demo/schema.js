// Demo-only: validate request data against the backend's own JSON Schemas,
// the way Pydantic (lax mode) validates the models they come from.
//
// contract/schemas.json is exported from the backend's models by
// app/tests/unit/test_demo_contract.py, which fails when a model changes until
// the file is refreshed, so the field types, defaults and limits here can't
// drift from the backend. Only the conversion rules and error messages below
// are Pydantic's, and contract/validation.json checks those against the real
// models. Model validators with their own logic (HealthCheckConfig's) are
// written out by hand in mockApi.js.

import schemas from "./contract/schemas.json";
import defaultConfig from "./default-config.json";

const DEFS = schemas.$defs;
const clone = (value) => JSON.parse(JSON.stringify(value));
const isObject = (value) =>
  typeof value === "object" && value !== null && !Array.isArray(value);

// The JSON Schema leaves out defaults made by a default_factory. Every one is
// inside AutoHealConfig, whose full default instance is default-config.json
// (itself checked against the backend), so take those defaults from there.
const MODEL_DEFAULTS = { AutoHealConfig: defaultConfig };
for (const [field, property] of Object.entries(
  DEFS.AutoHealConfig.properties,
)) {
  if (property.$ref)
    MODEL_DEFAULTS[refName(property.$ref)] = defaultConfig[field];
}

function refName(ref) {
  return ref.slice(ref.lastIndexOf("/") + 1);
}

const fail = (type, msg) => ({ error: { type, msg } });

// The JSON Schema keywords this file implements. A refreshed schemas.json
// using any other (enum, maxLength, pattern, ...) would be silently ignored,
// so schema.test.js fails on one until it is implemented here.
export const SUPPORTED_KEYWORDS = new Set([
  "$defs",
  "$ref",
  "additionalProperties",
  "anyOf",
  "default",
  "description",
  "items",
  "maximum",
  "minimum",
  "properties",
  "required",
  "title",
  "type",
]);

/** Pydantic's lax int: booleans, whole floats and integer strings convert. */
export function laxInt(value) {
  if (typeof value === "boolean") return { value: value ? 1 : 0 };
  if (typeof value === "number" && Number.isFinite(value)) {
    // Beyond int64 (a JS number can't tell a big integer from a float here).
    if (Math.abs(value) >= 2 ** 63) {
      return fail(
        "int_parsing_size",
        "Unable to parse input string as an integer, exceeded maximum size",
      );
    }
    if (Number.isInteger(value)) return { value };
    return fail(
      "int_from_float",
      "Input should be a valid integer, got a number with a fractional part",
    );
  }
  if (typeof value === "string") {
    // Digits with single underscores between them, optionally ".0..."
    if (/^\s*[+-]?\d+(?:_\d+)*(?:\.0+)?\s*$/.test(value)) {
      return { value: Number.parseInt(value.replaceAll("_", ""), 10) };
    }
    return fail(
      "int_parsing",
      "Input should be a valid integer, unable to parse string as an integer",
    );
  }
  return fail("int_type", "Input should be a valid integer");
}

const DIGITS = String.raw`\d(?:_?\d)*`;
const FLOAT_STRING = new RegExp(
  String.raw`^[+-]?(?:${DIGITS}(?:\.(?:${DIGITS})?)?|\.${DIGITS})(?:[eE][+-]?${DIGITS})?$`,
);

/** Pydantic's lax float: numbers, booleans and Python float() strings. */
function laxFloat(value) {
  if (typeof value === "number") return { value };
  if (typeof value === "boolean") return { value: value ? 1 : 0 };
  if (typeof value === "string") {
    const text = value.trim();
    if (FLOAT_STRING.test(text)) {
      return { value: Number(text.replaceAll("_", "")) };
    }
    const special = text.toLowerCase().replace(/^\+/, "");
    if (["inf", "infinity", "-inf", "-infinity"].includes(special)) {
      return { value: special.startsWith("-") ? -Infinity : Infinity };
    }
    return fail(
      "float_parsing",
      "Input should be a valid number, unable to parse string as a number",
    );
  }
  return fail("float_type", "Input should be a valid number");
}

const TRUE_STRINGS = new Set(["1", "on", "t", "true", "y", "yes"]);
const FALSE_STRINGS = new Set(["0", "off", "f", "false", "n", "no"]);
const BOOL_PARSING = [
  "bool_parsing",
  "Input should be a valid boolean, unable to interpret input",
];

/** Pydantic's lax bool: 0/1 and yes/no style strings convert. */
function laxBool(value) {
  if (typeof value === "boolean") return { value };
  if (typeof value === "number" && Number.isInteger(value)) {
    if (value === 0 || value === 1) return { value: value === 1 };
    return fail(...BOOL_PARSING);
  }
  if (typeof value === "string") {
    const text = value.toLowerCase();
    if (TRUE_STRINGS.has(text)) return { value: true };
    if (FALSE_STRINGS.has(text)) return { value: false };
    return fail(...BOOL_PARSING);
  }
  return fail("bool_type", "Input should be a valid boolean");
}

const SCALARS = {
  integer: laxInt,
  number: laxFloat,
  boolean: laxBool,
  string: (value) =>
    typeof value === "string"
      ? { value }
      : fail("string_type", "Input should be a valid string"),
};

/** Validate `value` against one property schema; push errors onto `errors`. */
function validateValue(schema, value, loc, errors, options) {
  if (schema.$ref)
    return validateModel(refName(schema.$ref), value, loc, errors, options);
  if (schema.anyOf) {
    // Only Optional[X] is used: null, or the one other branch.
    if (value === null) return null;
    return validateValue(
      schema.anyOf.find((branch) => branch.type !== "null"),
      value,
      loc,
      errors,
      options,
    );
  }
  if (schema.type === "array") {
    if (!Array.isArray(value)) {
      errors.push({
        type: "list_type",
        loc,
        msg: "Input should be a valid list",
      });
      return undefined;
    }
    return value.map((item, index) =>
      validateValue(schema.items, item, [...loc, index], errors, options),
    );
  }
  if (schema.type === "object") {
    if (!isObject(value)) {
      errors.push({
        type: "dict_type",
        loc,
        msg: "Input should be a valid dictionary",
      });
      return undefined;
    }
    const result = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = validateValue(
        schema.additionalProperties,
        item,
        [...loc, key],
        errors,
        options,
      );
    }
    return result;
  }
  const { value: converted, error } = SCALARS[schema.type](value);
  if (error) {
    errors.push({ ...error, loc });
    return undefined;
  }
  if (schema.minimum !== undefined && converted < schema.minimum) {
    errors.push({
      type: "greater_than_equal",
      loc,
      msg: `Input should be greater than or equal to ${schema.minimum}`,
    });
  } else if (schema.maximum !== undefined && converted > schema.maximum) {
    errors.push({
      type: "less_than_equal",
      loc,
      msg: `Input should be less than or equal to ${schema.maximum}`,
    });
  }
  return converted;
}

/**
 * Model.model_validate(value): every field in the model's order, unknown keys
 * dropped, missing ones defaulted (or "Field required"). Errors are pushed onto
 * `errors` with locations under `loc`; the result is only usable if none were.
 * With `fastapiBody`, a nested model that isn't an object gets the message
 * FastAPI's request-body validation gives instead of model_validate's.
 */
export function validateModel(name, value, loc, errors, options = {}) {
  const model = DEFS[name];
  if (!isObject(value)) {
    errors.push(
      options.fastapiBody
        ? {
            type: "model_attributes_type",
            loc,
            msg: "Input should be a valid dictionary or object to extract fields from",
          }
        : {
            type: "model_type",
            loc,
            msg: `Input should be a valid dictionary or instance of ${model.title}`,
          },
    );
    return undefined;
  }
  const required = new Set(model.required ?? []);
  const result = {};
  for (const [field, property] of Object.entries(model.properties)) {
    if (Object.hasOwn(value, field)) {
      result[field] = validateValue(
        property,
        value[field],
        [...loc, field],
        errors,
        options,
      );
    } else if (required.has(field)) {
      errors.push({
        type: "missing",
        loc: [...loc, field],
        msg: "Field required",
      });
    } else if (Object.hasOwn(property, "default")) {
      result[field] = clone(property.default);
    } else {
      // A default_factory field: always inside AutoHealConfig (see above).
      result[field] = clone(MODEL_DEFAULTS[name][field]);
    }
  }
  return result;
}
