import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DemoBanner from "./DemoBanner.jsx";
import { DemoEngine } from "./engine.js";

let engine;

const row = (name) => screen.getByText(name).closest("tr");

beforeEach(() => {
  engine = new DemoEngine();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DemoBanner", () => {
  it("says the demo is simulated and shows the version", () => {
    render(<DemoBanner engine={engine} version="v2.7.0" />);
    expect(
      screen.getByText("Simulated demo: no real containers."),
    ).toBeInTheDocument();
    expect(screen.getByText("v2.7.0")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Install Autoheal" }),
    ).toHaveAttribute(
      "href",
      "https://github.com/TommyE123/docker-autoheal#readme",
    );
    expect(
      screen.getByText(/checks every 5s, 10s cooldown/),
    ).toBeInTheDocument();
  });

  it("lists the containers with the actions that apply to each", () => {
    render(<DemoBanner engine={engine} version="v" />);
    const web = within(row("shop-web-1"));
    for (const name of [
      "Fail health check",
      "Crash",
      "Crash loop",
      "Stop (exit 0)",
    ]) {
      expect(web.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(web.queryByRole("button", { name: "Fix app" })).toBeNull();

    const worker = within(row("shop-worker-1"));
    expect(worker.getByText("stopped")).toBeInTheDocument();
    expect(worker.getByText("crashes after every start")).toBeInTheDocument();
    expect(worker.getByRole("button", { name: "Fix app" })).toBeInTheDocument();
    expect(worker.queryByRole("button", { name: "Crash" })).toBeNull();

    expect(
      within(row("shop-api-1")).getByText("health check failing"),
    ).toBeInTheDocument();
    expect(
      within(row("grafana")).getByText("(not monitored)"),
    ).toBeInTheDocument();
  });

  it("drives the engine and re-renders on changes", async () => {
    const user = userEvent.setup();
    render(<DemoBanner engine={engine} version="v" />);

    await user.click(
      within(row("shop-web-1")).getByRole("button", {
        name: "Fail health check",
      }),
    );
    expect(
      within(row("shop-web-1")).getByText("health check failing"),
    ).toBeInTheDocument();

    await user.click(
      within(row("shop-web-1")).getByRole("button", { name: "Fix app" }),
    );
    expect(within(row("shop-web-1")).getByText("working")).toBeInTheDocument();

    await user.click(
      within(row("shop-db-1")).getByRole("button", { name: "Crash" }),
    );
    expect(within(row("shop-db-1")).getByText("stopped")).toBeInTheDocument();

    await user.click(
      within(row("grafana")).getByRole("button", { name: "Stop (exit 0)" }),
    );
    expect(within(row("grafana")).getByText("stopped")).toBeInTheDocument();

    await user.click(
      within(row("shop-web-1")).getByRole("button", { name: "Crash loop" }),
    );
    expect(
      within(row("shop-web-1")).getByText("crashes after every start"),
    ).toBeInTheDocument();

    act(() => engine.quarantined.add("compose:shop:web#1"));
    act(() => engine._emit());
    expect(
      within(row("shop-web-1")).getByText("quarantined"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Reset demo/ }));
    expect(within(row("shop-web-1")).getByText("running")).toBeInTheDocument();
    expect(within(row("shop-db-1")).getByText("running")).toBeInTheDocument();
  });

  it("hides and shows the controls", async () => {
    const user = userEvent.setup();
    render(<DemoBanner engine={engine} version="v" />);
    const toggle = screen.getByRole("button", { name: "Hide controls" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Try it" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("starts collapsed on narrow screens", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    render(<DemoBanner engine={engine} version="v" />);
    expect(screen.getByRole("button", { name: "Try it" })).toBeInTheDocument();
  });
});
