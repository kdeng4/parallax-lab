import { expect, test } from '@playwright/test';

test('public page only requests public data and shows no invented results or settings', async ({ page }) => {
  const privateRequests: string[] = [];
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/v1/')) privateRequests.push(r.url()); });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Meet the agents.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Momentum', exact: true })).toBeVisible();
  await expect(page.getByText('No published results yet.')).toBeVisible();
  await expect(page.getByTestId('public-performance')).toHaveCount(0);
  await expect(page.getByTestId('market-overview')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'New experiment' })).toHaveCount(0);
  await expect(page.getByText('Starting capital')).toHaveCount(0);
  expect(privateRequests).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/public-mobile.png', fullPage: true });
});

test('licensed projection renders all agent lines and a distinguishable market benchmark', async ({ page }) => {
  await page.route('**/api/public/dashboard', route => route.fulfill({ json: {
    agents: [{ id: 'one', name: 'Research One' }, { id: 'two', name: 'Research Two' }],
    study: { id: 'test-only', mode: 'historical_paper_replay', recorded_at: '2026-10-12T19:00:00Z' },
    series: [{ id: 'one', name: 'Research One', benchmark: false, points: [{ date: '2026-10-01T00:00:00Z', value: 100 }, { date: '2026-10-09T00:00:00Z', value: 102 }] },
      { id: 'two', name: 'Research Two', benchmark: false, points: [{ date: '2026-10-01T00:00:00Z', value: 100 }, { date: '2026-10-09T00:00:00Z', value: 99 }] },
      { id: 'benchmark', name: 'S&P 500 · SPY', benchmark: true, points: [{ date: '2026-10-01T00:00:00Z', value: 100 }, { date: '2026-10-09T00:00:00Z', value: 101 }] }],
    activities: [{ id: 'trade', agent: 'Research One', action: 'buy', symbol: 'AAPL', session_date: '2026-10-02' }],
  } }));
  await page.goto('/');
  const chart = page.getByTestId('public-performance');
  await expect(chart.locator('svg path')).toHaveCount(3);
  await expect(chart.locator('svg path[stroke-dasharray]')).toHaveCount(1);
  await expect(page.getByText('Bought', { exact: true })).toBeVisible();
  await chart.getByRole('button', { name: 'Research One' }).click();
  await expect(chart.locator('svg path')).toHaveCount(2);
  await page.getByLabel('Inspect performance date').fill('0');
  await expect(chart.getByText('100.00', { exact: true })).toHaveCount(2);
  await page.screenshot({ path: 'test-results/public-chart.png', fullPage: true });
});

test('sign-in page reports unconfigured GitHub without offering password registration', async ({ page }) => {
  await page.goto('/auth/sign-in');
  await expect(page.getByText('Owner sign-in is awaiting GitHub setup.', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Password', { exact: true })).toHaveCount(0);
});
