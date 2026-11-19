import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const renderMock = vi.fn();
const createRootMock = vi.fn(() => ({ render: renderMock }));

vi.mock("react-dom/client", () => ({
  default: { createRoot: createRootMock },
}));

vi.mock("bootstrap/dist/css/bootstrap.min.css", () => ({}));
vi.mock("bootstrap-icons/font/bootstrap-icons.css", () => ({}));
vi.mock("./styles/App.css", () => ({}));

beforeEach(() => {
  vi.resetModules();
  createRootMock.mockClear();
  renderMock.mockClear();
  document.body.innerHTML = '<div id="root"></div>';
});

describe("main entry point", () => {
  it("mounts the app onto the #root element inside BrowserRouter and StrictMode", async () => {
    await import("./main.jsx");

    const rootElement = document.getElementById("root");
    expect(createRootMock).toHaveBeenCalledWith(rootElement);
    expect(renderMock).toHaveBeenCalledTimes(1);

    const tree = renderMock.mock.calls[0][0];
    expect(tree.props.children.type.name).toBe("BrowserRouter");
  });

  it("registers the service worker immediately on startup", async () => {
    await import("./main.jsx");
    // Import after resetModules so this is the instance main.jsx received.
    const { registerSW } = await import("virtual:pwa-register");

    expect(registerSW).toHaveBeenCalledTimes(1);
    expect(registerSW).toHaveBeenCalledWith({ immediate: true });
  });
});

describe("main entry point in the demo build", () => {
  const renderDemo = vi.fn();
  vi.doMock("./demo/index.jsx", () => ({ renderDemo }));

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("hands the root to the demo and registers no service worker", async () => {
    vi.stubEnv("MODE", "demo");
    await import("./main.jsx");
    const { registerSW } = await import("virtual:pwa-register");

    await vi.waitFor(() => expect(renderDemo).toHaveBeenCalledTimes(1));
    expect(renderDemo.mock.calls[0][0]).toBe(
      createRootMock.mock.results[0].value,
    );
    expect(renderMock).not.toHaveBeenCalled();
    expect(registerSW).not.toHaveBeenCalled();
  });
});
