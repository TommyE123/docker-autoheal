import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UptimeKumaMappings from "./UptimeKumaMappings";

const containers = [
  {
    id: "d0c4e7aa9912",
    stable_id: "proj_web-app",
    name: "web-app",
    status: "running",
  },
];
const monitors = [{ friendly_name: "web-monitor" }];

describe("UptimeKumaMappings", () => {
  it("disables Add until both a container and monitor are selected, then submits the mapping", async () => {
    const user = userEvent.setup();
    const onAddMapping = vi.fn();

    render(
      <UptimeKumaMappings
        mappings={[]}
        monitors={monitors}
        containers={containers}
        onAddMapping={onAddMapping}
        onDeleteMapping={vi.fn()}
      />,
    );

    const addButton = screen.getByRole("button", { name: /^add$/i });
    expect(addButton).toBeDisabled();

    const containerSelect = screen.getByLabelText("Container");
    const monitorSelect = screen.getByLabelText("Monitor");
    await user.selectOptions(containerSelect, "d0c4e7aa9912");
    await user.selectOptions(monitorSelect, "web-monitor");

    expect(addButton).toBeEnabled();
    await user.click(addButton);

    expect(onAddMapping).toHaveBeenCalledWith({
      container_id: "d0c4e7aa9912",
      monitor_friendly_name: "web-monitor",
    });
  });

  it("calls onDeleteMapping with the mapped container id when Delete is clicked", async () => {
    const user = userEvent.setup();
    const onDeleteMapping = vi.fn();

    render(
      <UptimeKumaMappings
        mappings={[
          {
            container_id: "proj_web-app",
            monitor_friendly_name: "web-monitor",
            auto_mapped: false,
          },
        ]}
        monitors={monitors}
        containers={containers}
        onAddMapping={vi.fn()}
        onDeleteMapping={onDeleteMapping}
      />,
    );

    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(onDeleteMapping).toHaveBeenCalledWith("proj_web-app");
  });

  it("lists unmapped containers and monitors first, each group alphabetical", () => {
    const unsortedContainers = [
      { id: "c1", stable_id: "zeta", name: "zeta", status: "running" },
      { id: "c2", stable_id: "Alpha", name: "Alpha", status: "running" },
      { id: "c3", stable_id: "beta", name: "beta", status: "running" },
      // Docker ID differs from the stable ID the mapping is stored under
      {
        id: "c4",
        stable_id: "proj_mapped-a",
        name: "mapped-a",
        status: "running",
      },
    ];
    const unsortedMonitors = [
      { friendly_name: "zulu" },
      { friendly_name: "mapped-mon" },
      { friendly_name: "Bravo" },
      { friendly_name: "alpha" },
    ];

    render(
      <UptimeKumaMappings
        mappings={[
          {
            container_id: "proj_mapped-a",
            monitor_friendly_name: "mapped-mon",
          },
        ]}
        monitors={unsortedMonitors}
        containers={unsortedContainers}
        onAddMapping={vi.fn()}
        onDeleteMapping={vi.fn()}
      />,
    );

    const optionValues = (label) =>
      Array.from(screen.getByLabelText(label).querySelectorAll("option"))
        .map((o) => o.value)
        .filter(Boolean);

    expect(optionValues("Container")).toEqual(["c2", "c3", "c1", "c4"]);
    expect(optionValues("Monitor")).toEqual([
      "alpha",
      "Bravo",
      "zulu",
      "mapped-mon",
    ]);
    expect(unsortedContainers[0].name).toBe("zeta");
  });

  it("shows the container name for a mapping stored under a stable id that differs from the docker id", () => {
    render(
      <UptimeKumaMappings
        mappings={[
          {
            container_id: "proj_web",
            monitor_friendly_name: "web-monitor",
            auto_mapped: false,
          },
        ]}
        monitors={monitors}
        containers={[
          {
            id: "d0c4e7aa9912",
            stable_id: "proj_web",
            name: "web-app",
            status: "running",
          },
        ]}
        onAddMapping={vi.fn()}
        onDeleteMapping={vi.fn()}
      />,
    );

    const cell = screen.getByRole("cell", { name: "web-app" });
    expect(cell).toBeInTheDocument();
    expect(screen.queryByText("proj_web")).not.toBeInTheDocument();
  });
});
