import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DemoBanner from "./DemoBanner.jsx";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DemoBanner", () => {
  it("says the data is sample data and shows the version", () => {
    render(<DemoBanner version="v2.7.0" />);
    expect(
      screen.getByText("Demo with sample data: no real containers."),
    ).toBeInTheDocument();
    expect(screen.getByText("v2.7.0")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Install Autoheal" }),
    ).toHaveAttribute(
      "href",
      "https://github.com/TommyE123/docker-autoheal#readme",
    );
  });

  it("resets by reloading the page", async () => {
    const user = userEvent.setup();
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(<DemoBanner version="v" />);
    await user.click(screen.getByRole("button", { name: "Reset demo" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
