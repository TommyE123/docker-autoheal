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

  it.each([
    [2, "PENDING"],
    [3, "MAINTENANCE"],
    [undefined, "UNKNOWN"],
  ])("labels monitor status %s as %s", (status, label) => {
    render(
      <UptimeKumaMonitorsList
        monitors={[{ friendly_name: "m", status }]}
        mappings={[]}
        containers={[]}
      />,
    );

    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("falls back to the raw id when the mapped container is unknown, and matches id prefixes", () => {
    render(
      <UptimeKumaMonitorsList
        monitors={[
          { friendly_name: "a", status: 1 },
          { friendly_name: "b", status: 1 },
        ]}
        mappings={[
          { monitor_friendly_name: "a", container_id: "gone999" },
          { monitor_friendly_name: "b", container_id: "abc" },
        ]}
        containers={[{ id: "abc123456", name: "web-app" }]}
      />,
    );

    expect(screen.getByText("gone999")).toBeInTheDocument();
    expect(screen.getByText("web-app")).toBeInTheDocument();
  });
});
