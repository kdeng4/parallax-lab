import { expect, test } from '@playwright/test';

test('owner can save additional tickers without triggering data calls, and select them in experiments', async ({ page, request }) => {
  const original = (await (await request.get('/api/v1/market/watchlist')).json()).symbols;
  let marketCalls = 0;
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/v1/market/overview') marketCalls += 1; });
  try {
    await page.goto('/workspace');
    await expect(page.getByTestId('market-overview').getByRole('heading', { name: 'US market watchlist' })).toBeVisible();
    const callsBeforeSave = marketCalls;
    await page.getByLabel('Tickers, separated by commas').fill('tsla, AMD, BRK.B');
    await page.getByRole('button', { name: 'Save tickers' }).click();
    await expect(page.getByText('Saved. Use Check data to fetch your updated list.')).toBeVisible();
    expect(marketCalls).toBe(callsBeforeSave);
    await expect(page.getByTestId('market-overview').getByRole('rowheader', { name: /TSLA/ })).toBeVisible();
    await page.getByRole('button', { name: /New experiment/ }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('Market').locator('option')).toHaveText(['TSLA', 'AMD', 'BRK-B']);
    await page.keyboard.press('Escape');
    await page.reload();
    await expect(page.getByLabel('Tickers, separated by commas')).toHaveValue('TSLA, AMD, BRK-B');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  } finally {
    await request.post('/api/v1/market/watchlist', { data: { symbols: original } });
  }
});

test('cloud model selection submits bounded checkpoints and shows provider failures', async ({ page }) => {
  await page.route('**/api/v1/catalog', async route => {
    const response = await route.fetch();
    const catalog = await response.json();
    await route.fulfill({ json: { ...catalog, models: [...catalog.models, { id: 'openai:gpt-6-luna', name: 'GPT-6 Luna', provider: 'OpenAI', description: 'Test transport only' }], openai: { configured: true, max_calls_per_experiment: 6, max_calls_per_minute: 6, max_calls_per_day: 24 } } });
  });
  let submitted: Record<string, unknown> | undefined;
  await page.route('**/api/v1/experiments', async route => {
    if (route.request().method() === 'POST') {
      submitted = route.request().postDataJSON();
      await route.fulfill({ status: 503, json: { detail: 'Provider declined the test request; no experiment was saved.' } });
    } else await route.continue();
  });
  await page.goto('/workspace');
  await page.getByRole('button', { name: /New experiment/ }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Momentum', { exact: true }).uncheck();
  await dialog.getByLabel('GPT-6 Luna', { exact: true }).check();
  await dialog.getByLabel('Decision checkpoints').selectOption('3');
  await expect(dialog.getByText(/3 billable OpenAI calls/)).toBeVisible();
  await dialog.getByRole('button', { name: /Run experiment/ }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Provider declined the test request; no experiment was saved.');
  expect(submitted?.decision_checkpoints).toBe(3);
  expect(submitted?.model_ids).toContain('openai:gpt-6-luna');
});
