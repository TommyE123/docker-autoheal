import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DisableUptimeKumaModal from "./DisableUptimeKumaModal";

describe("DisableUptimeKumaModal", () => {
  it("confirms disabling the integration when the confirm button is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();

    render(
      <DisableUptimeKumaModal show onHide={vi.fn()} onConfirm={onConfirm} />,
    );

    await user.click(
      screen.getByRole("button", { name: /disable integration/i }),
    );

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("does not render its content when show is false", () => {
    render(
      <DisableUptimeKumaModal
        show={false}
        onHide={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(
      screen.queryByText(/disable uptime-kuma integration/i),
    ).not.toBeInTheDocument();
  });
});
