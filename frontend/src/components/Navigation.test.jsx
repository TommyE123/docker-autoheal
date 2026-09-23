import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Navigation from "./Navigation";

function renderAt(path, systemStatus) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Navigation systemStatus={systemStatus} />
    </MemoryRouter>,
  );
}

describe("Navigation", () => {
  it("marks the nav link matching the current route as active", () => {
    renderAt("/events", null);

    expect(screen.getByRole("link", { name: /events/i })).toHaveClass("active");
    expect(screen.getByRole("link", { name: /containers/i })).not.toHaveClass(
      "active",
    );
  });

  it("shows monitoring status and container counts when systemStatus is available", () => {
    renderAt("/containers", {
      monitoring_active: true,
      docker_connected: true,
      monitored_containers: 3,
      total_containers: 5,
    });

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("3/5 monitored")).toBeInTheDocument();
  });

  it("shows Inactive when monitoring is not active", () => {
    renderAt("/containers", {
      monitoring_active: false,
      docker_connected: true,
      monitored_containers: 0,
      total_containers: 5,
    });

    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });
});
