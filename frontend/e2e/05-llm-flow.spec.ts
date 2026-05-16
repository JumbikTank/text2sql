import { expect, test } from '@playwright/test';
import { resetConnections, resetLocalStorage, TEST_CONNECTION, BACKEND } from './helpers';

/**
 * Full end-to-end against the real LLM.
 *
 * Each of these tests triggers a real `/api/messages` call that goes through
 * the full agent pipeline (vector search → table filter → SQL generation →
 * controller → execution → natural-language answer). They're slow and cost
 * real API tokens — keep the number of prompts small.
 */

test.setTimeout(180_000);

async function ensureActiveConnectionWithScan(request: import('@playwright/test').APIRequestContext): Promise<string> {
  await resetConnections(request);
  const save = await request.post(`${BACKEND}/api/connections`, { data: TEST_CONNECTION });
  expect(save.status()).toBe(201);
  const saved = await save.json();

  const activate = await request.post(`${BACKEND}/api/connections/${saved.id}/activate`);
  expect([200, 204]).toContain(activate.status());

  // Scanner is disabled in .env, so activate doesn't schedule scans.
  // Trigger one explicitly so the notes_<id> table has embeddings the LLM can search.
  const scan = await request.post(`${BACKEND}/api/connections/${saved.id}/scan`);
  expect(scan.status()).toBe(200);
  const scanResult = await scan.json();
  expect(scanResult.if_success).toBe(true);

  return saved.id;
}

test.beforeEach(async ({ page, request }) => {
  await ensureActiveConnectionWithScan(request);
  await resetLocalStorage(page);
});

test('sends a natural-language question and receives a SQL-backed answer', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: new RegExp(TEST_CONNECTION.name) })).toBeVisible();

  const textarea = page.getByPlaceholder('Ask a question about your data...');
  await textarea.fill('How many customers are there?');
  await textarea.press('Enter');

  // The user bubble appears immediately.
  await expect(page.getByText('How many customers are there?')).toBeVisible();

  // Thinking indicator while the agent runs.
  await expect(page.getByText('Thinking...')).toBeVisible();

  // Assistant response eventually arrives. The pipeline involves vector
  // search + multiple LLM calls + SQL execution, so we give it up to 2 min.
  await expect(page.getByText('Thinking...')).not.toBeVisible({ timeout: 150_000 });

  // At least one assistant message is present.
  await expect(page.getByText('Assistant').first()).toBeVisible();

  // The response should reference the customers table via a SELECT query.
  const codeBlock = page.locator('pre').filter({ hasText: /SELECT/i }).first();
  await expect(codeBlock).toBeVisible({ timeout: 5_000 });
  await expect(codeBlock).toContainText(/customers/i);
});

test('Stop button aborts an in-flight request', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: new RegExp(TEST_CONNECTION.name) })).toBeVisible();

  const textarea = page.getByPlaceholder('Ask a question about your data...');
  await textarea.fill('Give me a breakdown of orders by product category and month for the last year');
  await textarea.press('Enter');

  // Give the request a moment to actually start.
  await expect(page.getByText('Thinking...')).toBeVisible();

  // Stop button should now replace the Send button.
  await page.getByRole('button', { name: 'Stop' }).click();

  // After abort, loading clears and no error banner appears.
  await expect(page.getByText('Thinking...')).not.toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('heading', { name: 'Error' })).toHaveCount(0);
});

test('follow-up question reuses context from the prior answer', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: new RegExp(TEST_CONNECTION.name) })).toBeVisible();

  const textarea = page.getByPlaceholder('Ask a question about your data...');

  // First question establishes context.
  await textarea.fill('Show me all products');
  await textarea.press('Enter');
  await expect(page.getByText('Thinking...')).not.toBeVisible({ timeout: 150_000 });
  const firstSqlCount = await page.locator('pre').filter({ hasText: /SELECT/i }).count();
  expect(firstSqlCount).toBeGreaterThanOrEqual(1);

  // Follow-up should reuse the tables cached in the previous turn.
  await textarea.fill('Only the first 3, ordered by price');
  await textarea.press('Enter');
  await expect(page.getByText('Thinking...')).not.toBeVisible({ timeout: 150_000 });

  // A new SQL block should appear — 2+ SELECT blocks in total.
  await expect(page.locator('pre').filter({ hasText: /SELECT/i }).nth(1)).toBeVisible({
    timeout: 5_000,
  });
});
