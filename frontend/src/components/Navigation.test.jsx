import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { setApiKey, clearApiKey } from "../services/api";
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

  describe("API key item", () => {
    afterEach(() => clearApiKey());

    it("is hidden when no key is stored", () => {
      render(
        <MemoryRouter>
          <Navigation systemStatus={null} onApiKeyClick={vi.fn()} />
        </MemoryRouter>,
      );

      expect(
        screen.queryByRole("button", { name: /api key/i }),
      ).not.toBeInTheDocument();
    });

    it("opens the key prompt when a key is stored", async () => {
      const user = userEvent.setup();
      const onApiKeyClick = vi.fn();
      setApiKey("abc");
      render(
        <MemoryRouter>
          <Navigation systemStatus={null} onApiKeyClick={onApiKeyClick} />
        </MemoryRouter>,
      );

      await user.click(screen.getByRole("button", { name: /api key/i }));

      expect(onApiKeyClick).toHaveBeenCalled();
    });
  });
});
