import { describe, it, expect, afterEach, vi } from "vitest";
import axios from "axios";
import api from "../services/api";
import { addAnalytics, installMockApi, renderDemo } from "./index.jsx";
import { DemoEngine } from "./engine.js";

const originalApiAdapter = api.defaults.adapter;
const originalAxiosAdapter = axios.defaults.adapter;

afterEach(() => {
  api.defaults.adapter = originalApiAdapter;
  axios.defaults.adapter = originalAxiosAdapter;
  document.body.innerHTML = "";
});

describe("installMockApi", () => {
  it("routes the shared API instance and global axios to the engine", async () => {
    const engine = new DemoEngine();
    installMockApi(engine);
    expect((await api.get("/status")).data.total_containers).toBe(6);
    expect((await axios.get("/health")).data.status).toBe("healthy");
  });
});

describe("addAnalytics", () => {
  it("adds the Cloudflare beacon only when a token is set", () => {
    addAnalytics("");
    addAnalytics(undefined);
    expect(document.querySelector("script")).toBeNull();
    addAnalytics("abc123");
    const script = document.querySelector("script");
    expect(script.src).toBe(
      "https://static.cloudflareinsights.com/beacon.min.js",
    );
    expect(script.defer).toBe(true);
    expect(JSON.parse(script.dataset.cfBeacon)).toEqual({ token: "abc123" });
  });
});

describe("renderDemo", () => {
  it("starts the engine and renders the banner and app under the base path", () => {
    const root = { render: vi.fn() };
    const engine = renderDemo(root, {
      BASE_URL: "/docker-autoheal/",
      VITE_DEMO_VERSION: "v2.7.0",
      VITE_CF_ANALYTICS_TOKEN: "",
    });
    try {
      expect(engine.running).toBe(true);
      expect(document.title).toBe("Docker Auto-Heal Demo");
      const router = root.render.mock.calls[0][0].props.children;
      expect(router.type.name).toBe("BrowserRouter");
      expect(router.props.basename).toBe("/docker-autoheal");
      const [banner, app] = router.props.children;
      expect(banner.props).toMatchObject({ engine, version: "v2.7.0" });
      expect(app.type.name).toBe("App");
    } finally {
      engine.stop();
    }
  });

  it("falls back to the root path and a development label", () => {
    const root = { render: vi.fn() };
    const engine = renderDemo(root, {});
    engine.stop();
    const router = root.render.mock.calls[0][0].props.children;
    expect(router.props.basename).toBe("/");
    expect(router.props.children[0].props.version).toBe("a development build");
  });
});
