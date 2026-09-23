import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UptimeKumaMappings from "./UptimeKumaMappings";

const containers = [{ id: "abc123", name: "web-app", status: "running" }];
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

    const [containerSelect, monitorSelect] = screen.getAllByRole("combobox");
    await user.selectOptions(containerSelect, "abc123");
    await user.selectOptions(monitorSelect, "web-monitor");

    expect(addButton).toBeEnabled();
    await user.click(addButton);

    expect(onAddMapping).toHaveBeenCalledWith({
      container_id: "abc123",
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
            container_id: "abc123",
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

    expect(onDeleteMapping).toHaveBeenCalledWith("abc123");
  });
});
