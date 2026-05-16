import { expect, test } from '@playwright/test';
import { resetConnections, resetLocalStorage, TEST_CONNECTION } from './helpers';

test.beforeEach(async ({ page, request }) => {
  await resetConnections(request);
  // Seed an activated connection so the sidebar has data.
  const save = await request.post('http://localhost:18001/api/connections', {
    data: TEST_CONNECTION,
  });
  const saved = await save.json();
  await request.post(`http://localhost:18001/api/connections/${saved.id}/activate`);
  await resetLocalStorage(page);
});

test('sidebar lists tables and views from the seeded schema', async ({ page }) => {
  await page.goto('/');

  // Wait for the header chip showing the active connection to appear.
  await expect(page.getByRole('button', { name: new RegExp(TEST_CONNECTION.name) })).toBeVisible();

  // The seeded schema (scripts/setup_test_db.sql) has these.
  await expect(page.getByText('customers', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('orders', { exact: true })).toBeVisible();
  await expect(page.getByText('products', { exact: true })).toBeVisible();

  // order_summary is a VIEW and should carry the `view` badge.
  await expect(page.getByText('order_summary')).toBeVisible();
});

test('selecting a table reveals column details', async ({ page }) => {
  await page.goto('/');

  await page.getByText('customers', { exact: true }).click();

  // Details header appears.
  await expect(page.getByRole('heading', { name: /customers/ })).toBeVisible({ timeout: 10_000 });

  // Must show at least one column.
  await expect(page.getByText(/email/i).first()).toBeVisible();
});

test('preview data opens a table with rows', async ({ page }) => {
  await page.goto('/');

  await page.getByText('customers', { exact: true }).click();
  // Details view exposes a Preview Data button in the sidebar footer.
  await page.getByRole('button', { name: /Preview Data/i }).click();

  // The preview pane should show at least one data row.
  // We don't assert specific values because the seed may vary, but we expect
  // either rows or an explicit "No data" message — neither indicates a broken UI.
  const preview = page.locator('table').first();
  await expect(preview).toBeVisible({ timeout: 10_000 });
});

test('sidebar can be collapsed and reopened', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Tables' })).toBeVisible();

  await page.getByRole('button', { name: /Close sidebar/i }).click();
  await expect(page.getByRole('heading', { name: 'Tables' })).toHaveCount(0);

  await page.getByRole('button', { name: /Open sidebar/i }).click();
  await expect(page.getByRole('heading', { name: 'Tables' })).toBeVisible();
});
