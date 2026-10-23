import { describe, it } from "vitest";
import { RuleTester } from "eslint";
import local from "./jsx-no-duplicate-props.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

ruleTester.run(
  "jsx-no-duplicate-props",
  local.rules["jsx-no-duplicate-props"],
  {
    valid: [
      '<div id="a" className="b" />',
      // Spreads may override earlier props on purpose; only literal
      // attribute names are compared.
      '<div {...props} id="a" {...rest} />',
      // Names are case-sensitive, as in React.
      '<div onClick={a} onclick="b" />',
      '<svg xlink:href="#a" href="#b" />',
      // Each element is checked on its own.
      '<div id="a"><span id="a" /></div>',
    ],
    invalid: [
      {
        code: '<div id="a" id="b" />',
        errors: [{ messageId: "duplicate", data: { name: "id" } }],
      },
      {
        code: "<Foo onClick={a} {...props} onClick={b} />",
        errors: [{ messageId: "duplicate", data: { name: "onClick" } }],
      },
      {
        code: '<svg xlink:href="#a" xlink:href="#b" />',
        errors: [{ messageId: "duplicate", data: { name: "xlink:href" } }],
      },
      {
        code: "<input disabled disabled disabled />",
        errors: [
          { messageId: "duplicate", data: { name: "disabled" } },
          { messageId: "duplicate", data: { name: "disabled" } },
        ],
      },
    ],
  },
);
