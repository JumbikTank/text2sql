import { expect, test } from '@playwright/test';
import { resetConnections, resetLocalStorage } from './helpers';

test.beforeEach(async ({ page, request }) => {
  await resetConnections(request);
  await resetLocalStorage(page);
});

test('renders empty state with welcome card and feature tiles', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle(/Text2SQL/i);
  await expect(page.getByRole('heading', { name: 'Welcome to Text2SQL' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Natural Language' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'SQL Generation' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Data Export' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Smart Context' })).toBeVisible();
});

test('sidebar prompts to connect a database when there is no active connection', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByText(/Connect to a database to browse tables/i)
  ).toBeVisible();
});

test('header shows "No connection" before any connection is added', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /No connection/i })).toBeVisible();
});

test('chat input is present, enforces 2000 char limit, and refuses empty submit', async ({ page }) => {
  await page.goto('/');
  const textarea = page.getByPlaceholder('Ask a question about your data...');
  await expect(textarea).toBeVisible();

  // Enter is bound to send; with empty input, no message appears.
  await textarea.press('Enter');
  await expect(page.getByText('You', { exact: true })).toHaveCount(0);

  const longInput = 'a'.repeat(2500);
  await textarea.fill(longInput);
  // Textarea clamps to maxLength.
  await expect(textarea).toHaveValue(/^a{2000}$/);
  await expect(page.getByText(/2000 \/ 2000/)).toBeVisible();
});
