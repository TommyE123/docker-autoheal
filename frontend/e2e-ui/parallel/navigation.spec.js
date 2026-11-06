import { test, expect } from "../fixtures.js";

const pages = [
  {
    link: "Containers",
    path: "/containers",
    heading: { name: /Containers$/ },
  },
  { link: "Events", path: "/events", heading: { name: "Event Log" } },
  {
    link: "Notifications",
    path: "/notifications",
    heading: { name: "Notifications", exact: true },
  },
  {
    link: "Configuration",
    path: "/config",
    heading: { name: "Monitor Settings" },
  },
];

test(
  "the app starts on the containers dashboard",
  { tag: "@smoke" },
  async ({ page }) => {
    await page.goto("/");

    // "/" redirects to /containers client-side.
    await expect(page).toHaveURL(/\/containers$/);
    await expect(page.getByText("Docker Auto-Heal Service")).toBeVisible();
    // The Dashboard only renders once /api/status has succeeded.
    await expect(
      page.getByRole("heading", { name: "Dashboard" }),
    ).toBeVisible();
    await expect(page.getByText("Total Containers")).toBeVisible();
  },
);

test(
  "every page is reachable from the navigation bar",
  { tag: "@smoke" },
  async ({ page }) => {
    await page.goto("/containers");

    const navigation = page.getByRole("navigation");
    // Visit every other page, then return to Containers.
    for (const { link, path, heading } of [...pages.slice(1), pages[0]]) {
      await navigation.getByRole("link", { name: link }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", heading)).toBeVisible();
    }
  },
);

for (const { path, heading } of pages) {
  test(
    `${path} loads directly and survives a refresh`,
    { tag: "@regression" },
    async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", heading)).toBeVisible();

      await page.reload();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", heading)).toBeVisible();
    },
  );
}

test("the theme toggle switches between light and dark and persists across reloads", async ({
  page,
}) => {
  await page.goto("/containers");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-bs-theme", "light");

  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(html).toHaveAttribute("data-bs-theme", "dark");
  await expect(
    page.getByRole("button", { name: "Switch to light mode" }),
  ).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await expect(html).toHaveAttribute("data-bs-theme", "dark");
  await expect(page.getByText("Total Containers")).toBeVisible();

  await page.getByRole("button", { name: "Switch to light mode" }).click();
  await expect(html).toHaveAttribute("data-bs-theme", "light");
});

test("a saved theme is applied before the app renders", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  // Block the app bundle so only the inline script can have set the theme.
  await page.route(/\/assets\/.*\.js$/, (route) => route.abort());
  await page.goto("/containers");

  await expect(page.locator("html")).toHaveAttribute("data-bs-theme", "dark");
  await expect(page.getByText("Docker Auto-Heal Service")).toHaveCount(0);
});
