import { fileURLToPath } from "node:url";
import {
  defineConfig,
  configDefaults,
  coverageConfigDefaults,
} from "vitest/config";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { workbox } from "./workbox.config.js";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
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
    outDir: "../static",
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
    // Playwright UI E2E specs run via `npm run test:ui-e2e`, not Vitest.
    exclude: [...configDefaults.exclude, "e2e-ui/**"],
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
      ],
    },
  },
});
