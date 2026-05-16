import type { APIRequestContext, Page } from '@playwright/test';

export const BACKEND = 'http://localhost:18001';

/**
 * Delete every saved connection via the backend API so tests start clean.
 */
export async function resetConnections(request: APIRequestContext): Promise<void> {
  const res = await request.get(`${BACKEND}/api/connections`);
  if (!res.ok()) return;
  const body = await res.json();
  for (const conn of body.connections ?? []) {
    await request.delete(`${BACKEND}/api/connections/${conn.id}`);
  }
}

/**
 * Clear the chat store in localStorage so tests get a fresh UI.
 */
export async function resetLocalStorage(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      window.localStorage.clear();
    } catch {
      /* no-op */
    }
  });
}

export const TEST_CONNECTION = {
  name: 'e2e-test',
  host: 'localhost',
  port: 5433,
  database: 'testdb',
  username: 'testuser',
  password: 'testpass',
  ssl_mode: 'disable' as const,
};
