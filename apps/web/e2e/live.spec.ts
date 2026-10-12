import { expect, test } from '@playwright/test';

const id = '00000000-0000-4000-8000-000000000010';
const snapshotId = '00000000-0000-4000-8000-000000000020';
const accounts = ['GPT-6 Luna / Balanced momentum', 'GPT-6.1 Sol / Capital preservation'].map((name, i) => ({
  id: `account-${i}`, name, model_id: i ? 'openai:gpt-6.1-sol' : 'openai:gpt-6-luna', strategy_id: i ? 'conservative' : 'balanced',
  status: 'active', equity: i ? 99000 : 102000, return_pct: i ? -1 : 2,
  book: { cash: '50000', holdings: { AAPL: '100' }, receivables: {} },
}));
const study = { id, name: 'Browser forward transport', status: 'active', started_at: '2026-10-12T14:00:00Z', created_at: '2026-10-12T14:00:00Z', last_tick_at: '2026-10-13T14:05:00Z', last_error: null,
  config: { symbols: ['AAPL', 'TSLA'], initial_cash: 100000, timezone: 'America/Toronto', window_start: '09:45', window_end: '10:45' }, accounts,
  round: { day: '2026-10-13', stage: 'executing', snapshot_id: snapshotId, snapshot_hash: 'a'.repeat(64) },
  points: [{ timestamp: '2026-10-12T14:00:00Z', returns: { 'account-0': 0, 'account-1': 0 }, benchmark_pct: 0 },
    { timestamp: '2026-10-13T14:05:00Z', returns: { 'account-0': 2, 'account-1': -1 }, benchmark_pct: 1 }],
  events: [{ id: 'decision', timestamp: '2026-10-13T14:01:00Z', type: 'decision', account_id: 'account-0', message: 'Observed decision', details: { shared_snapshot_id: snapshotId } }],
};

test('ongoing controls select multiple tickers, pairs, initial funds and window without backdating', async ({ page }) => {
  await page.route('**/api/v1/catalog', async route => {
    const base = await (await route.fetch()).json();
    await route.fulfill({ json: { ...base, models: [{ id: 'openai:gpt-6-luna', name: 'GPT-6 Luna', provider: 'OpenAI' }, { id: 'openai:gpt-6.1-sol', name: 'GPT-6.1 Sol', provider: 'OpenAI' }], live: { available: true, requirement: null, scheduler_configured: true } } });
  });
  let submitted: Record<string, unknown> | undefined;
  await page.route('**/api/v1/studies', route => route.request().method() === 'POST'
    ? (submitted = route.request().postDataJSON(), route.fulfill({ status: 503, json: { detail: 'Test transport: current source unavailable. No study created.' } }))
    : route.fulfill({ json: { studies: [] } }));
  await page.goto('/workspace');
  await page.getByRole('button', { name: 'New ongoing study', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Study name').fill('Future research');
  await dialog.getByLabel('Study tickers, separated by commas').fill('AAPL, TSLA, AMD');
  await dialog.getByLabel('Initial capital per pair (USD)').fill('5000');
  await dialog.getByLabel('Capital preservation', { exact: true }).check();
  await dialog.getByLabel('Daily window starts').fill('10:00');
  await dialog.getByLabel('Daily window ends').fill('11:00');
  await dialog.getByRole('button', { name: 'Start ongoing study' }).click();
  await expect(dialog.getByRole('alert')).toContainText('No study created.');
  expect(submitted?.symbols).toEqual(['AAPL', 'TSLA', 'AMD']);
  expect(submitted?.model_ids).toHaveLength(2); expect(submitted?.strategy_ids).toHaveLength(2);
  expect(submitted?.initial_cash).toBe(5000); expect(submitted?.window_start).toBe('10:00');
  expect(submitted).not.toHaveProperty('start_date'); expect(submitted).not.toHaveProperty('seed');
  await page.keyboard.press('Escape'); await expect(dialog).not.toBeVisible();
});

test('each pair plots a percent line, SPY is dashed, shared news can be inspected and owner pause works', async ({ page }) => {
  let status = 'active';
  await page.route('**/api/v1/studies', route => route.fulfill({ json: { studies: [{ ...study, status }] } }));
  await page.route(`**/api/v1/studies/${id}`, route => route.fulfill({ json: { ...study, status } }));
  await page.route(`**/api/v1/studies/${id}/pause`, route => { status = 'paused'; return route.fulfill({ json: { ...study, status } }); });
  await page.route(`**/api/v1/studies/${id}/snapshots/${snapshotId}`, route => route.fulfill({ json: { id: snapshotId, hash: 'a'.repeat(64), captured_at: '2026-10-13T14:00:00Z',
    quotes: { AAPL: { price: 100, as_of: '2026-10-13T14:00:00Z', source: 'Test transport' } },
    news: [{ id: 'story', title: 'Common observed article', summary: 'Every participant saw this exact test article.', url: 'https://example.com/article', published_at: '2026-10-13T13:00:00Z', provider: 'Test transport' }],
    news_sources: [{ name: 'Test transport', status: 'ok', fetched_at: '2026-10-13T14:00:00Z' }], events: [],
  } }));
  await page.goto('/workspace');
  const panel = page.getByTestId('live-studies');
  await expect(panel.getByRole('heading', { name: study.name })).toBeVisible();
  const chart = panel.getByTestId('percent-chart');
  await expect(chart.locator('svg path')).toHaveCount(3);
  await expect(chart.locator('svg path[stroke-dasharray]')).toHaveCount(1);
  await expect(chart.getByText('+2.00%', { exact: true })).toBeVisible();
  await expect(chart.getByText('-1.00%', { exact: true })).toBeVisible();
  await chart.getByLabel('Inspect performance time').fill('0');
  await expect(chart.locator('.percent-readout').getByText('0.00%', { exact: true })).toHaveCount(3);
  await panel.getByRole('button', { name: 'Inspect shared news and prices' }).click();
  await expect(panel.getByRole('heading', { name: 'Exactly what every agent could see' })).toBeVisible();
  await expect(panel.getByRole('link', { name: 'Common observed article' })).toHaveAttribute('href', 'https://example.com/article');
  await panel.getByRole('button', { name: 'Pause study' }).click();
  await expect(panel.getByRole('button', { name: 'Resume study' })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Check current window' })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/ongoing-study-mobile.png', fullPage: true });
});

test('unapproved identity cannot start, pause or process a study', async ({ page }) => {
  await page.route('**/api/session', route => route.fulfill({ json: { canView: false, canEdit: false, email: null, reason: 'sign_in' } }));
  await page.route('**/api/v1/studies', route => route.fulfill({ json: { studies: [study] } }));
  await page.route(`**/api/v1/studies/${id}`, route => route.fulfill({ json: study }));
  await page.goto('/workspace');
  await expect(page.getByRole('button', { name: 'New ongoing study', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Pause study' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Check current window' })).toBeDisabled();
});
