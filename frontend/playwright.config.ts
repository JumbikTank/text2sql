import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for end-to-end UI tests.
 *
 * Expects the backend (port 18001), frontend (port 13000), and the test
 * Postgres (docker-compose.test.yml on port 5433) to be running. The test
 * Postgres was seeded by scripts/setup_test_db.sql.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:13000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
