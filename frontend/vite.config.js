import { fileURLToPath } from "node:url";
import {
  defineConfig,
  configDefaults,
  coverageConfigDefaults,
} from "vitest/config";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { workbox } from "./workbox.config.js";

// `--mode demo` builds the public browser demo (src/demo/, deployed to GitHub
// Pages by .github/workflows/demo-pages.yml): served from a sub-path, written
// to dist/ instead of the backend's static/, and without a service worker.
const DEMO_BASE = "/docker-autoheal/";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  base: mode === "demo" ? DEMO_BASE : "/",
  plugins: [
    react(),
    // The demo has no PWA: drop the manifest link, whose root-relative URLs
    // would point outside the Pages sub-path.
    {
      name: "demo-no-manifest",
      transformIndexHtml: (html) =>
        mode === "demo" ? html.replace(/<link rel="manifest"[^>]*>/, "") : html,
    },
    VitePWA({
      disable: mode === "demo",
      // The client registers the service worker itself (src/main.jsx), so the
      // plugin must not inject its own registerSW.js script into index.html.
      injectRegister: false,
      registerType: "autoUpdate",
      // Use the hand-maintained public/manifest.json (already linked from
      // index.html) instead of generating one.
      manifest: false,
      workbox,
    }),
  ],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:3131",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:3131",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: mode === "demo" ? "dist" : "../static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    // `virtual:pwa-register` only exists inside a Vite build; tests get a mock.
    alias: {
      "virtual:pwa-register": fileURLToPath(
        new URL("./src/test/pwa-register-stub.js", import.meta.url),
      ),
    },
    // Playwright specs run via `npm run test:ui-e2e` and `npm run test:demo-e2e`, not Vitest.
    exclude: [...configDefaults.exclude, "e2e-ui/**", "e2e-demo/**"],
    setupFiles: ["./src/test/setup.js"],
    globalSetup: ["./src/test/globalSetup.js"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      reportsDirectory: "./coverage",
      // Vitest 4+ only reports files loaded during tests; list the source
      // globs so untested files still show as uncovered, as before the upgrade.
      include: ["src/**/*.{js,jsx}"],
      // globalSetup runs in the main process before worker pools start, so
      // v8 coverage instrumentation never sees it execute; excluding it
      // keeps coverage % from being diluted by a file that can never show
      // as covered no matter how it's tested.
      // Playwright config and specs run in a browser against the Docker image,
      // not under Vitest, so they can never show as covered here either.
      exclude: [
        ...coverageConfigDefaults.exclude,
        "src/test/globalSetup.js",
        "playwright.ui.config.js",
        "e2e-ui/**",
        "playwright.demo.config.js",
        "e2e-demo/**",
      ],
    },
  },
}));
