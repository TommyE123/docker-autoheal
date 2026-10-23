import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  BrowserRouter,
  useNavigate,
  useLocation,
} from "react-router-dom";

vi.mock("./services/api", () => ({
  getSystemStatus: vi.fn(),
  enableMaintenanceMode: vi.fn(),
  disableMaintenanceMode: vi.fn(),
  getContainers: vi.fn().mockResolvedValue({ data: [] }),
  updateContainerSelection: vi.fn(),
  restartContainer: vi.fn(),
  unquarantineContainer: vi.fn(),
  getContainerDetails: vi.fn(),
}));

vi.mock("./components/Dashboard", () => ({
  default: () => <div>Dashboard stub</div>,
}));
vi.mock("./components/ContainersPage", () => ({
  default: () => <div>ContainersPage stub</div>,
}));
vi.mock("./components/EventsPage", () => ({
  default: () => <div>EventsPage stub</div>,
}));
vi.mock("./components/NotificationsPage", () => ({
  default: () => <div>NotificationsPage stub</div>,
}));
vi.mock("./components/ConfigPage", () => ({
  default: () => <div>ConfigPage stub</div>,
}));
vi.mock("./components/MaintenanceModal", () => ({
  default: () => <div>MaintenanceModal stub</div>,
}));

import { getSystemStatus } from "./services/api";
import App from "./App";

const STATUS = {
  total_containers: 2,
  monitored_containers: 1,
  quarantined_containers: 0,
  monitoring_active: true,
  docker_connected: true,
  maintenance_mode: false,
};

const ALL_PAGE_STUBS = [
  "Dashboard stub",
  "ContainersPage stub",
  "EventsPage stub",
  "NotificationsPage stub",
  "ConfigPage stub",
];

function expectOnlyStubsVisible(visibleStubs) {
  for (const stub of ALL_PAGE_STUBS) {
    if (visibleStubs.includes(stub)) {
      expect(screen.getByText(stub)).toBeInTheDocument();
    } else {
      expect(screen.queryByText(stub)).not.toBeInTheDocument();
    }
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  getSystemStatus.mockResolvedValue({ data: STATUS });
});

afterEach(() => {
  // replaceState (not pushState) so this reset doesn't itself add a history
  // entry, since the BrowserRouter test asserts on back-navigation.
  window.history.replaceState({}, "", "/");
});

describe("App routing", () => {
  it.each([
    { path: "/containers", stub: "ContainersPage stub" },
    { path: "/events", stub: "EventsPage stub" },
    { path: "/notifications", stub: "NotificationsPage stub" },
    { path: "/config", stub: "ConfigPage stub" },
  ])("renders the matching page stub for $path", async ({ path, stub }) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText(stub)).toBeInTheDocument();

    const expectedStubs =
      path === "/containers"
        ? ["Dashboard stub", "ContainersPage stub"]
        : [stub];
    for (const expected of expectedStubs) {
      await screen.findByText(expected);
    }
    expectOnlyStubsVisible(expectedStubs);
  });

  const NAV_LINKS = [
    { label: "Containers", linkName: /containers/i },
    { label: "Events", linkName: /events/i },
    { label: "Notifications", linkName: /notifications/i },
    { label: "Configuration", linkName: /configuration/i },
  ];

  it.each([
    { label: "Containers", path: "/containers", stub: "ContainersPage stub" },
    { label: "Events", path: "/events", stub: "EventsPage stub" },
    {
      label: "Notifications",
      path: "/notifications",
      stub: "NotificationsPage stub",
    },
    { label: "Configuration", path: "/config", stub: "ConfigPage stub" },
  ])(
    "clicking the $label nav link navigates to $path and marks it active",
    async ({ label, path, stub }) => {
      const user = userEvent.setup();
      const startPath = path === "/containers" ? "/events" : "/containers";
      const { linkName } = NAV_LINKS.find((link) => link.label === label);

      render(
        <MemoryRouter initialEntries={[startPath]}>
          <App />
        </MemoryRouter>,
      );

      await user.click(screen.getByRole("link", { name: linkName }));

      expect(await screen.findByText(stub)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: linkName })).toHaveClass(
        "active",
      );

      const otherLinks = NAV_LINKS.filter((link) => link.label !== label);
      for (const { linkName: otherName } of otherLinks) {
        expect(screen.getByRole("link", { name: otherName })).not.toHaveClass(
          "active",
        );
      }
    },
  );

  it("renders nav link hrefs for each route and the external API docs link", async () => {
    render(
      <MemoryRouter initialEntries={["/containers"]}>
        <App />
      </MemoryRouter>,
    );

    await screen.findByText("ContainersPage stub");

    expect(screen.getByRole("link", { name: /containers/i })).toHaveAttribute(
      "href",
      "/containers",
    );
    expect(screen.getByRole("link", { name: /events/i })).toHaveAttribute(
      "href",
      "/events",
    );
    expect(
      screen.getByRole("link", { name: /notifications/i }),
    ).toHaveAttribute("href", "/notifications");
    expect(
      screen.getByRole("link", { name: /configuration/i }),
    ).toHaveAttribute("href", "/config");

    const docsLink = screen.getByRole("link", { name: /api docs/i });
    expect(docsLink).toHaveAttribute("href", "/docs");
    expect(docsLink).toHaveAttribute("target", "_blank");
  });

  it("redirects '/' to /containers using replace, so back navigation skips it", async () => {
    const user = userEvent.setup();

    function LocationProbe() {
      const navigate = useNavigate();
      const location = useLocation();
      return (
        <div>
          <div data-testid="pathname">{location.pathname}</div>
          <button onClick={() => navigate(-1)}>back</button>
        </div>
      );
    }

    render(
      <MemoryRouter initialEntries={["/events", "/"]} initialIndex={1}>
        <LocationProbe />
        <App />
      </MemoryRouter>,
    );

    await screen.findByText("ContainersPage stub");
    expect(screen.getByTestId("pathname")).toHaveTextContent("/containers");

    await user.click(screen.getByRole("button", { name: "back" }));

    expect(await screen.findByText("EventsPage stub")).toBeInTheDocument();
    expect(screen.getByTestId("pathname")).toHaveTextContent("/events");
  });

  it("renders nothing for an unknown route without throwing, but keeps the nav bar", async () => {
    render(
      <MemoryRouter initialEntries={["/does-not-exist"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(getSystemStatus).toHaveBeenCalled();
    });

    expectOnlyStubsVisible([]);
    expect(screen.getByText("Docker Auto-Heal Service")).toBeInTheDocument();
  });

  it("works with a real BrowserRouter: click-navigation and back button update the URL", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/events");

    render(
      <BrowserRouter>
        <App />
      </BrowserRouter>,
    );

    expect(await screen.findByText("EventsPage stub")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /configuration/i }));

    expect(window.location.pathname).toBe("/config");
    expect(await screen.findByText("ConfigPage stub")).toBeInTheDocument();

    window.history.back();

    await waitFor(() => {
      expect(screen.getByText("EventsPage stub")).toBeInTheDocument();
    });
    expect(window.location.pathname).toBe("/events");
  });
});
