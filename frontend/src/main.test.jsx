import { describe, it, expect, vi, beforeEach } from "vitest";

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
});
