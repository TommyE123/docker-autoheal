// Vitest stand-in for the build-time `virtual:pwa-register` module that
// vite-plugin-pwa generates. See `resolve.alias` in vite.config.js.
import { vi } from "vitest";

export const registerSW = vi.fn();
