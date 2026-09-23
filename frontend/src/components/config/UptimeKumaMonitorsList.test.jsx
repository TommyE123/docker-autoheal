import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import UptimeKumaMonitorsList from "./UptimeKumaMonitorsList";

describe("UptimeKumaMonitorsList", () => {
  it("shows mapped monitors linked to their container name and unmapped ones as such", () => {
    const monitors = [
      { friendly_name: "web-monitor", status: 1 },
      { friendly_name: "db-monitor", status: 0 },
    ];
    const mappings = [
      { monitor_friendly_name: "web-monitor", container_id: "abc123" },
    ];
    const containers = [{ id: "abc123", name: "web-app" }];

    render(
      <UptimeKumaMonitorsList
        monitors={monitors}
        mappings={mappings}
        containers={containers}
      />,
    );

    expect(screen.getByText("web-monitor")).toBeInTheDocument();
    expect(screen.getByText("UP")).toBeInTheDocument();
    expect(screen.getByText("web-app")).toBeInTheDocument();

    expect(screen.getByText("db-monitor")).toBeInTheDocument();
    expect(screen.getByText("DOWN")).toBeInTheDocument();
    expect(screen.getByText("Not Mapped")).toBeInTheDocument();
  });
});
