import { test, expect } from '@playwright/test';

test('main UI renders from the Docker-served application', async ({ page }) => {
  await page.goto('/');

  // "/" redirects to /containers client-side.
  await expect(page.getByText('Docker Auto-Heal Service')).toBeVisible();
  await expect(page).toHaveURL(/\/containers$/);

  // The Dashboard only renders once /api/status has succeeded, so this
  // exercises the browser -> frontend -> API path.
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByText('Total Containers')).toBeVisible();
});
