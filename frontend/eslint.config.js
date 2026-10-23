import js from "@eslint/js";
import globals from "globals";
import eslintReact from "@eslint-react/eslint-plugin";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import eslintConfigPrettier from "eslint-config-prettier";
import local from "./eslint-rules/jsx-no-duplicate-props.js";

export default [
  { ignores: ["dist", "coverage", "test-results-ui", "playwright-report-ui"] },
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "@eslint-react": eslintReact,
      local,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      // One-to-one replacements for the eslint-plugin-react rules this config
      // used to enable; see "React lint rules" in docs/developer/frontend.md.
      // react/jsx-no-undef and react/jsx-uses-vars need no replacement:
      // ESLint 10 tracks JSX references, so core no-undef and no-unused-vars
      // cover them.
      "@eslint-react/no-missing-component-display-name": "error",
      "@eslint-react/no-missing-key": "error",
      "@eslint-react/jsx-no-comment-textnodes": "error",
      "local/jsx-no-duplicate-props": "error",
      "@eslint-react/dom-no-unsafe-target-blank": "error",
      "@eslint-react/jsx-no-children-prop": "error",
      "@eslint-react/jsx-no-children-prop-with-children": "error",
      "@eslint-react/dom-no-dangerously-set-innerhtml-with-children": "error",
      "@eslint-react/no-component-will-mount": "error",
      "@eslint-react/no-component-will-receive-props": "error",
      "@eslint-react/no-component-will-update": "error",
      "@eslint-react/dom-no-render": "error",
      "@eslint-react/dom-no-hydrate": "error",
      "@eslint-react/no-direct-mutation-state": "error",
      "@eslint-react/dom-no-find-dom-node": "error",
      "@eslint-react/dom-no-render-return-value": "error",
      "@eslint-react/dom-no-unknown-property": "error",
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  {
    files: ["**/playwright.ui.config.js", "**/e2e-ui/**/*.js"],
    languageOptions: { globals: globals.node },
  },
  eslintConfigPrettier,
];
