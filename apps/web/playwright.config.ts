import { defineConfig, devices } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const databaseDirectory = mkdtempSync(join(tmpdir(), 'parallax-lab-e2e-'));

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: 'http://127.0.0.1:3100',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
  },
  webServer: [
    {
      command: 'uv run --frozen python tests/browser_server.py',
      cwd: '../api',
      url: 'http://127.0.0.1:8010/api/v1/health',
      env: { PARALLAX_DATABASE_URL: `sqlite:///${join(databaseDirectory, 'research.db')}`, PARALLAX_MARKET_SOURCE: 'synthetic', PARALLAX_MARKET_NETWORK: '0' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --hostname 127.0.0.1 --port 3100',
      url: 'http://127.0.0.1:3100',
      env: { API_BASE_URL: 'http://127.0.0.1:8010', NEXT_TELEMETRY_DISABLED: '1', PARALLAX_LOCAL_WRITE_ACCESS: '1' },
      timeout: 90_000,
      reuseExistingServer: false,
    },
  ],
});
