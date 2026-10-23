// Local replacement for eslint-plugin-react's `jsx-no-duplicate-props`, which
// @eslint-react/eslint-plugin leaves to the TypeScript compiler. This frontend
// is plain JavaScript, so without this rule a repeated JSX attribute would
// silently let the last value win.

function attributeName(attribute) {
  const { name } = attribute;
  if (name.type === "JSXNamespacedName") {
    return `${name.namespace.name}:${name.name.name}`;
  }
  return name.name;
}

const jsxNoDuplicateProps = {
  meta: {
    type: "problem",
    docs: {
      description: "Disallow duplicate attributes on the same JSX element",
    },
    schema: [],
    messages: {
      duplicate: "Duplicate prop `{{name}}` found on this JSX element.",
    },
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        const seen = new Set();
        for (const attribute of node.attributes) {
          if (attribute.type !== "JSXAttribute") continue;
          const name = attributeName(attribute);
          if (seen.has(name)) {
            context.report({
              node: attribute,
              messageId: "duplicate",
              data: { name },
            });
          }
          seen.add(name);
        }
      },
    };
  },
};

export default {
  rules: { "jsx-no-duplicate-props": jsxNoDuplicateProps },
};
