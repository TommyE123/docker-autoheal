// Entry point for the demo build (`vite build --mode demo`) only. main.jsx
// imports this behind `import.meta.env.MODE === "demo"`, so production
// builds don't include any of the demo code.

import React from "react";
import axios from "axios";
import { BrowserRouter } from "react-router-dom";
import App from "../App.jsx";
import api from "../services/api";
import { DemoEngine } from "./engine.js";
import { createMockAdapter } from "./mockApi.js";
import DemoBanner from "./DemoBanner.jsx";

/** Route every API request (shared instance and global axios) to the engine. */
export function installMockApi(engine) {
  const adapter = createMockAdapter(engine);
  api.defaults.adapter = adapter;
  axios.defaults.adapter = adapter;
  return adapter;
}

/** Cloudflare Web Analytics: page views only, no cookies. Optional. */
export function addAnalytics(token, doc = document) {
  if (!token) return;
  const script = doc.createElement("script");
  script.defer = true;
  script.src = "https://static.cloudflareinsights.com/beacon.min.js";
  script.dataset.cfBeacon = JSON.stringify({ token });
  doc.body.appendChild(script);
}

export function renderDemo(root, env = import.meta.env) {
  const engine = new DemoEngine();
  installMockApi(engine);
  engine.start();
  addAnalytics(env.VITE_CF_ANALYTICS_TOKEN);
  document.title = "Docker Auto-Heal Demo";

  // BASE_URL is the Pages sub-path, e.g. "/docker-autoheal/".
  const basename = (env.BASE_URL ?? "/").replace(/\/+$/, "") || "/";
  root.render(
    <React.StrictMode>
      <BrowserRouter basename={basename}>
        <DemoBanner
          engine={engine}
          version={env.VITE_DEMO_VERSION || "a development build"}
        />
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  );
  return engine;
}
