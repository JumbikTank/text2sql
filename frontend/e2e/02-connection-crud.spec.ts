import { expect, test } from '@playwright/test';
import { resetConnections, resetLocalStorage, TEST_CONNECTION } from './helpers';

test.beforeEach(async ({ page, request }) => {
  await resetConnections(request);
  await resetLocalStorage(page);
});

test('add, test, save, and activate a connection end-to-end', async ({ page }) => {
  await page.goto('/');

  // Open connections modal from the header.
  await page.getByRole('button', { name: /No connection/i }).click();
  await expect(page.getByRole('heading', { name: 'Database Connections' })).toBeVisible();
  await expect(page.getByText('No connections yet')).toBeVisible();

  // Open the new-connection modal.
  await page.getByRole('button', { name: 'Add Connection' }).click();
  await expect(page.getByRole('heading', { name: 'New Connection' })).toBeVisible();

  // Fill in the form.
  await page.getByLabel('Connection Name').fill(TEST_CONNECTION.name);
  await page.getByLabel('Host').fill(TEST_CONNECTION.host);
  await page.getByLabel('Port').fill(String(TEST_CONNECTION.port));
  await page.getByLabel('Database').fill(TEST_CONNECTION.database);
  await page.getByLabel('Username').fill(TEST_CONNECTION.username);
  await page.getByLabel('Password').fill(TEST_CONNECTION.password);

  // Test the connection first; should report success with server version.
  await page.getByRole('button', { name: 'Test Connection' }).click();
  await expect(page.getByText('Connection successful')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/PostgreSQL/)).toBeVisible();

  // Save.
  await page.getByRole('button', { name: 'Save', exact: true }).click();

  // Back in the list: the new connection appears.
  await expect(page.getByRole('heading', { name: 'Database Connections' })).toBeVisible();
  await expect(page.getByText(TEST_CONNECTION.name)).toBeVisible();

  // It's not active yet.
  await expect(page.getByText('Active')).toHaveCount(0);

  // Activate via the row menu.
  await page.locator('button:has(svg.lucide-ellipsis-vertical)').first().click();
  await page.getByRole('button', { name: /Set Active/i }).click();

  await expect(page.getByText('Active')).toBeVisible();

  // Close the modal; header should now show the active connection name.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: new RegExp(TEST_CONNECTION.name) })).toBeVisible();
});

test('validation errors appear for missing required fields', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /No connection/i }).click();
  await page.getByRole('button', { name: 'Add Connection' }).click();

  await page.getByRole('button', { name: 'Save', exact: true }).click();

  await expect(page.getByText('Connection name is required')).toBeVisible();
  await expect(page.getByText('Database name is required')).toBeVisible();
  await expect(page.getByText('Username is required')).toBeVisible();
  await expect(page.getByText('Password is required')).toBeVisible();
});

test('editing a connection pre-fills fields except password', async ({ page, request }) => {
  // Seed a connection via the API.
  const res = await request.post('http://localhost:18001/api/connections', {
    data: TEST_CONNECTION,
  });
  expect(res.status()).toBe(201);
  const saved = await res.json();
  // Password must be masked in the response.
  expect(saved.password).toBe('********');

  await page.goto('/');
  await page.getByRole('button', { name: /No connection/i }).click();

  await page.locator('button:has(svg.lucide-ellipsis-vertical)').first().click();
  await page.getByRole('button', { name: 'Edit' }).click();

  await expect(page.getByRole('heading', { name: 'Edit Connection' })).toBeVisible();
  await expect(page.getByLabel('Connection Name')).toHaveValue(TEST_CONNECTION.name);
  await expect(page.getByLabel('Host')).toHaveValue(TEST_CONNECTION.host);
  await expect(page.getByLabel('Database')).toHaveValue(TEST_CONNECTION.database);
  // Password is not pre-filled for safety.
  await expect(page.getByLabel('Password')).toHaveValue('');

  // Update the name and save.
  await page.getByLabel('Connection Name').fill('e2e-test-renamed');
  await page.getByRole('button', { name: 'Update', exact: true }).click();
  await expect(page.getByText('e2e-test-renamed')).toBeVisible();
});

test('delete a connection removes it from the list', async ({ page, request }) => {
  await request.post('http://localhost:18001/api/connections', { data: TEST_CONNECTION });

  await page.goto('/');
  await page.getByRole('button', { name: /No connection/i }).click();

  // Accept the confirm() dialog.
  page.once('dialog', (dialog) => dialog.accept());

  await page.locator('button:has(svg.lucide-ellipsis-vertical)').first().click();
  await page.getByRole('button', { name: 'Delete' }).click();

  await expect(page.getByText('No connections yet')).toBeVisible();
});
