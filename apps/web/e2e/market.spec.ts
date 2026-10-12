import { expect, test } from '@playwright/test';

test('missing market credentials show empty values, never made-up prices', async ({ page }) => {
  await page.goto('/');
  const market = page.getByTestId('market-overview');
  await expect(market.getByRole('heading', { name: 'US market watchlist' })).toBeVisible();
  await expect(market.getByText('Feed disabled', { exact: true })).toHaveCount(9);
  await expect(market.locator('.market-value')).toHaveText(['—', '—', '—', '—']);
  await expect(market.getByText('US$0.00')).toHaveCount(0);
});

test('published values retain source dates, stale labels and mobile containment', async ({ page }) => {
  const retrieved = new Date().toISOString();
  const next = new Date(Date.now() + 21_600_000).toISOString();
  await page.route('**/api/v1/market/overview', route => route.fulfill({ json: {
    as_of: retrieved, refresh_interval_seconds: 21600, price_frequency: 'Completed daily sessions; not intraday quotes',
    indicator_basis: 'Split- and dividend-adjusted closes.', replay_ready: false,
    macro: [{ id: 'FXUSDCAD', label: 'USD / CAD', unit: 'CAD per USD', frequency: 'daily', value: 1.4271,
      change: .0031, as_of: '2026-10-09', status: 'ok', source: 'Bank of Canada', source_url: 'https://www.bankofcanada.ca/rates/', fetched_at: retrieved, next_refresh_at: next }],
    stocks: [{ symbol: 'SPY', source: 'Tiingo', source_url: 'https://www.tiingo.com/', status: 'stale', fetched_at: retrieved, next_refresh_at: next,
      data: { as_of: '2026-10-09', close: 500.25, adjusted_close: 500.25, change_pct: -.5, volume: 100000,
        indicators: { sma20: 502, sma50: 499, rsi14: 42, macd: null, macd_signal: null } } }],
  } }));
  await page.goto('/');
  const market = page.getByTestId('market-overview');
  await expect(market.getByText('1.4271', { exact: true })).toBeVisible();
  await expect(market.getByRole('cell', { name: /US\$500.25/ })).toBeVisible();
  await expect(market.getByText('Stale', { exact: true })).toBeVisible();
  await expect(market.getByText('-0.50%', { exact: true })).toBeVisible();
  await market.getByText('Source & freshness').click();
  await expect(market.getByRole('link', { name: 'Bank of Canada', exact: true })).toHaveAttribute('href', 'https://www.bankofcanada.ca/rates/');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
