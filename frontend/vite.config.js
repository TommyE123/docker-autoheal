import { defineConfig, configDefaults, coverageConfigDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:3131',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:3131',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    // Playwright E2E specs run via `npm run test:e2e`, not Vitest.
    exclude: [...configDefaults.exclude, 'e2e/**', 'e2e-ui/**'],
    setupFiles: ['./src/test/setup.js'],
    globalSetup: ['./src/test/globalSetup.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      reportsDirectory: './coverage',
      // globalSetup runs in the main process before worker pools start, so
      // v8 coverage instrumentation never sees it execute; excluding it
      // keeps coverage % from being diluted by a file that can never show
      // as covered no matter how it's tested.
      // Playwright config and specs run in a browser against the Docker image,
      // not under Vitest, so they can never show as covered here either.
      exclude: [
        ...coverageConfigDefaults.exclude,
        'src/test/globalSetup.js',
        'playwright.config.js',
        'playwright.ui.config.js',
        'e2e/**',
        'e2e-ui/**',
      ],
    },
  },
})

