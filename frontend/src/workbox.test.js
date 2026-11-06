import { describe, it, expect } from "vitest";
import { workbox } from "../workbox.config.js";

const apiRule = workbox.runtimeCaching.find(
  (rule) => rule.handler === "NetworkOnly",
);
const urlAt = (path) => ({ url: new URL(path, "http://localhost:3131") });

describe("Workbox config", () => {
  it("sends /api/* requests straight to the network", () => {
    expect(workbox.runtimeCaching).toHaveLength(1);
    expect(apiRule.urlPattern(urlAt("/api/containers"))).toBe(true);
    expect(apiRule.urlPattern(urlAt("/assets/index.js"))).toBe(false);
  });

  it("keeps /api/ and /health out of the SPA navigation fallback", () => {
    const denied = (path) =>
      workbox.navigateFallbackDenylist.some((re) => re.test(path));
    expect(denied("/api/containers")).toBe(true);
    expect(denied("/health")).toBe(true);
    expect(denied("/containers")).toBe(false);
    expect(denied("/events")).toBe(false);
  });

  it("updates automatically and drops outdated caches", () => {
    expect(workbox.cleanupOutdatedCaches).toBe(true);
    expect(workbox.skipWaiting).toBe(true);
    expect(workbox.clientsClaim).toBe(true);
  });

  it("does not precache the install screenshots", () => {
    expect(workbox.globIgnores).toContain("screenshot-*.png");
  });

  it("matches precached fonts that carry a bootstrap-icons hash query", () => {
    const ignored = (param) =>
      workbox.ignoreURLParametersMatching.some((re) => re.test(param));
    expect(ignored("e34853135f9e39acf64315236852cd5a")).toBe(true);
    // Workbox's own defaults stay in place.
    expect(ignored("utm_source")).toBe(true);
    expect(ignored("fbclid")).toBe(true);
    expect(ignored("page")).toBe(false);
  });
});
