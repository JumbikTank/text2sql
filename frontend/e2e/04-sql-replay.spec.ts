import { expect, test } from '@playwright/test';
import { resetConnections, resetLocalStorage, TEST_CONNECTION } from './helpers';

test.beforeEach(async ({ page, request }) => {
  await resetConnections(request);
  const save = await request.post('http://localhost:18001/api/connections', {
    data: TEST_CONNECTION,
  });
  const saved = await save.json();
  await request.post(`http://localhost:18001/api/connections/${saved.id}/activate`);

  // Pre-populate chat-storage in localStorage so we have an assistant message
  // with a SQL query to replay. This lets us exercise the replay flow (which
  // calls /api/sql directly) without going through the LLM.
  await page.addInitScript(() => {
    window.localStorage.setItem(
      'chat-storage',
      JSON.stringify({
        state: {
          messages: [
            {
              id: 'user-1',
              role: 'user',
              content: 'How many customers are there?',
              type: 'plain',
              timestamp: new Date().toISOString(),
            },
            {
              id: 'assistant-1',
              role: 'assistant',
              content: 'Here are the results.',
              type: 'text_with_csv',
              sql_query: 'SELECT count(*) AS n FROM customers',
              preview_data: '|   n |\n|----:|\n|   5 |',
              timestamp: new Date().toISOString(),
            },
          ],
        },
        version: 0,
      })
    );
  });
});

test('replay query button re-runs SQL and updates the message', async ({ page }) => {
  await page.goto('/');

  // Our seeded assistant message shows up with its SQL.
  await expect(page.getByText('SELECT count(*) AS n FROM customers')).toBeVisible();

  const replayBtn = page.getByRole('button', { name: /Replay Query/ });
  await expect(replayBtn).toBeVisible();

  await replayBtn.click();

  // Success toast appears.
  await expect(page.getByText('Query Replayed')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Query executed successfully in/)).toBeVisible();

  // "Last updated" timestamp appears after a replay.
  await expect(page.getByText(/Last updated:/)).toBeVisible();
});

test('download CSV button triggers a file download', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('button', { name: /Replay Query/ }).click();
  await expect(page.getByText('Query Replayed')).toBeVisible({ timeout: 15_000 });

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: /Download CSV/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
});

test('open in new tab produces a results window', async ({ page, context }) => {
  await page.goto('/');

  await page.getByRole('button', { name: /Replay Query/ }).click();
  await expect(page.getByText('Query Replayed')).toBeVisible({ timeout: 15_000 });

  const popupPromise = context.waitForEvent('page');
  await page.getByRole('button', { name: /Open in New Tab/ }).click();
  const popup = await popupPromise;

  await popup.waitForLoadState('domcontentloaded');
  await expect(popup).toHaveTitle(/Query Results/);
  await expect(popup.getByText('SELECT count(*) AS n FROM customers')).toBeVisible();
});

test('clear chat empties the message list', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('SELECT count(*) AS n FROM customers')).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: /Clear Chat/ }).click();

  await expect(page.getByRole('heading', { name: 'Welcome to Text2SQL' })).toBeVisible();
});
