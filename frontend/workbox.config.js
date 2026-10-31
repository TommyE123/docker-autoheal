// Workbox options for vite-plugin-pwa; kept separate so tests can assert them.
export const workbox = {
  cleanupOutdatedCaches: true,
  clientsClaim: true,
  skipWaiting: true,
  // Precache only what is needed to load the app shell; the large
  // install-dialog screenshots are fetched by the browser on demand.
  globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
  globIgnores: ["screenshot-*.png"],
  navigateFallback: "index.html",
  // API calls and the backend health endpoint are never answered by the
  // SPA shell.
  navigateFallbackDenylist: [/^\/api\//, /^\/health/],
  runtimeCaching: [
    {
      // NetworkOnly on purpose: NetworkFirst would store successful API
      // responses in Cache Storage and replay them when the backend is down.
      urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
      handler: "NetworkOnly",
    },
  ],
};
