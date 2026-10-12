import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function openWorkbench(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /new experiment/i }).first()).toBeVisible();
  await expect(page.getByTestId('equity-chart')).toBeVisible();
}

test('seeded dashboard renders persisted results without browser errors', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openWorkbench(page);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-CA');
  await expect(page).toHaveTitle('Parallax Lab — Trading research, measured.');
  await expect(page.getByRole('link', { name: 'Parallax Lab home' })).toBeVisible();
  await expect(page.getByText('US$100,000', { exact: true })).toBeVisible();
  const response = await request.get('/api/v1/experiments');
  expect(response.ok()).toBeTruthy();
  const experiments = (await response.json()).experiments;
  const seed = experiments.find((item: { name: string }) => item.name === 'Opening bell · baseline study');
  const detail = await (await request.get(`/api/v1/experiments/${seed.id}`)).json();
  expect(detail.data_source).toBe('synthetic');
  expect(detail.runs).toHaveLength(3);
  for (const run of detail.runs) {
    await expect(page.getByText(run.model_name, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByTestId('equity-chart')).toBeVisible();
  expect(errors).toEqual([]);
});

for (const comparison of ['models', 'strategies'] as const) {
  test(`creates and persists a fair ${comparison} experiment from the form`, async ({ page, request }) => {
    await openWorkbench(page);
    await page.getByRole('button', { name: /new experiment/i }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const name = `Browser ${comparison} study`;
    await dialog.getByLabel(/Experiment name/i).fill(name);
    await dialog.locator('input[name="comparison"]').nth(comparison === 'models' ? 0 : 1).check();
    await dialog.getByLabel('Replay bars').fill('90');
    await dialog.getByLabel('Dataset seed').fill('71');
    const result = page.waitForResponse((response) => response.url().endsWith('/api/v1/experiments') && response.request().method() === 'POST');
    await dialog.getByRole('button', { name: /Run experiment/i }).click();
    const response = await result;
    expect(response.status()).toBe(201);
    const detail = await response.json();
    expect(detail.comparison).toBe(comparison);
    expect(detail.runs.length).toBeGreaterThanOrEqual(2);
    const fixedFactor = comparison === 'models' ? 'strategy_id' : 'model_id';
    expect(new Set(detail.runs.map((run: Record<string, string>) => run[fixedFactor])).size).toBe(1);
    expect(detail.data_hash).toMatch(/^[a-f0-9]{64}$/);
    await expect(dialog).not.toBeVisible();
    await expect(page.getByLabel('Selected experiment')).toHaveValue(detail.id);
    expect((await request.get(`/api/v1/experiments/${detail.id}`)).ok()).toBeTruthy();
    await page.reload();
    await expect(page.getByLabel('Selected experiment')).toHaveValue(detail.id);
  });
}

test('optional experiment name works and dialog supports keyboard dismissal', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /new experiment/i }).first().click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('button', { name: /new experiment/i }).first().click();
  const result = page.waitForResponse((response) => response.url().endsWith('/api/v1/experiments') && response.request().method() === 'POST');
  await page.getByRole('dialog').getByRole('button', { name: /Run experiment/i }).click();
  expect((await result).status()).toBe(201);
  await expect(page.getByRole('dialog')).not.toBeVisible();
});

test('invalid participant selection stays local and can be corrected', async ({ page }) => {
  await openWorkbench(page);
  await page.getByRole('button', { name: /new experiment/i }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('input[name="comparison"]').first().check();
  const models = dialog.locator('input[name="models"]');
  let submissions = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/experiments') submissions += 1;
  });

  await models.nth(1).uncheck();
  await models.nth(2).uncheck();
  await dialog.getByRole('button', { name: /Run experiment/i }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Select at least two models to compare.');
  expect(submissions).toBe(0);
  await expect(dialog).toBeVisible();

  await models.nth(1).check();
  const created = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/experiments');
  await dialog.getByRole('button', { name: /Run experiment/i }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const detail = await response.json();
  expect(detail.runs).toHaveLength(2);
  expect(submissions).toBe(1);
  await expect(dialog).not.toBeVisible();
  await expect(page.getByLabel('Selected experiment')).toHaveValue(detail.id);
});

test('chart controls, account inspection, audit filtering and export use persisted data', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByTestId('equity-chart')).toBeVisible();
  const id = await page.getByLabel('Selected experiment').inputValue();
  const detail = await (await request.get(`/api/v1/experiments/${id}`)).json();
  await page.getByRole('button', { name: 'Last 60', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Last 60', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('img', { name: /Net account equity over 60 bars/ })).toBeVisible();
  await page.getByRole('button', { name: /^Inspect .* account$/ }).first().click();
  await expect(page.getByText('Available cash', { exact: true })).toBeVisible();

  const downloading = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export', exact: true }).click();
  const download = await downloading;
  const downloadedPath = await download.path();
  expect(downloadedPath).toBeTruthy();
  const record = JSON.parse(await readFile(downloadedPath!, 'utf8'));
  expect(record.id).toBe(id);
  expect(record.data_hash).toBe(detail.data_hash);
  expect(record.runs).toEqual(detail.runs);
  expect(record.events.length).toBeGreaterThan(0);

  await page.getByRole('button', { name: 'Audit trail', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Decision timeline' })).toBeVisible();
  await page.getByLabel('Event type', { exact: true }).selectOption('fill');
  const participant = detail.runs.find((run: { trade_count: number }) => run.trade_count > 0);
  const filtered = page.waitForResponse((response) => response.url().includes('/events?') && response.url().includes(`run_id=${participant.id}`));
  await page.getByLabel('Participant', { exact: true }).selectOption(participant.id);
  const events = await (await filtered).json();
  expect(events.total).toBe(participant.trade_count);
  expect(events.events.every((event: { type: string; run_id: string }) => event.type === 'fill' && event.run_id === participant.id)).toBeTruthy();
  await expect(page.getByTestId('audit-events').locator('details')).toHaveCount(Math.min(20, participant.trade_count));
  await page.getByTestId('audit-events').locator('summary').first().click();
  await expect(page.getByTestId('audit-events').locator('details[open] pre')).toContainText('before');
  await expect(page.getByTestId('audit-events').locator('details[open] pre')).toContainText('after');
});

test('switching audit experiments clears filters and displays the selected record', async ({ page, request }) => {
  const firstResponse = await request.post('/api/v1/experiments', { data: { name: 'Audit switch first', bars: 60, seed: 101 } });
  const secondResponse = await request.post('/api/v1/experiments', { data: { name: 'Audit switch second', bars: 60, seed: 102 } });
  expect(firstResponse.status()).toBe(201);
  expect(secondResponse.status()).toBe(201);
  const first = await firstResponse.json();
  const second = await secondResponse.json();

  await openWorkbench(page);
  await page.getByRole('button', { name: 'Audit trail', exact: true }).click();
  const experimentSelector = page.locator('#audit-experiment');
  await expect(experimentSelector).toHaveValue(second.id);

  await page.getByLabel('Event type', { exact: true }).selectOption('decision');
  const filteredResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/api/v1/experiments/${second.id}/events` && url.searchParams.get('run_id') === second.runs[0].id;
  });
  await page.getByLabel('Participant', { exact: true }).selectOption(second.runs[0].id);
  const filtered = await (await filteredResponse).json();
  expect(filtered.total).toBeGreaterThan(0);
  await expect(page.getByText(`${filtered.total} events`, { exact: true })).toBeVisible();

  const selectedEvents = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/v1/experiments/${first.id}/events`);
  await experimentSelector.selectOption(first.id);
  const response = await selectedEvents;
  const url = new URL(response.url());
  expect(url.searchParams.has('type')).toBe(false);
  expect(url.searchParams.has('run_id')).toBe(false);
  expect(url.searchParams.has('from_time')).toBe(false);
  expect(url.searchParams.has('to_time')).toBe(false);
  const unfiltered = await response.json();
  expect(unfiltered.total).toBeGreaterThan(filtered.total);
  await expect(page.getByLabel('Event type', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Participant', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Participant', { exact: true }).locator(`option[value="${second.runs[0].id}"]`)).toHaveCount(0);
  await expect(page.getByText(`${unfiltered.total} events`, { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Export full record' })).toHaveAttribute('href', `/api/v1/experiments/${first.id}/export`);
  const summaries = page.getByTestId('audit-events').locator('summary');
  await expect(summaries).toHaveCount(20);
  for (const [index, event] of unfiltered.events.slice(0, 4).entries()) {
    await expect(summaries.nth(index)).toContainText(event.message);
    await expect(summaries.nth(index)).toContainText(`#${event.sequence}`);
  }
});

test('mobile layout stays within viewport and can create an experiment', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const create = page.getByRole('button', { name: /new experiment/i }).first();
  await expect(create).toBeVisible();
  await expect(page.getByTestId('equity-chart')).toBeVisible();
  await expect(page.getByTestId('audit-events')).toBeVisible();
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflows).toBeFalsy();
  await create.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('button', { name: /Run experiment/i })).toBeVisible();
});

test('connection failure is actionable and retry restores the workspace', async ({ page }) => {
  await page.route('**/api/v1/catalog', (route) => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert').filter({ hasText: 'research data' })).toContainText('load the research data');
  await page.unroute('**/api/v1/catalog');
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(page.getByTestId('equity-chart')).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'research data' })).not.toBeVisible();
});

test('failed experiment selection never presents previous results as the new experiment', async ({ page, request }) => {
  const first = await (await request.post('/api/v1/experiments', { data: { name: 'Selection target', bars: 60 } })).json();
  const current = await (await request.post('/api/v1/experiments', { data: { name: 'Current selection', bars: 60 } })).json();
  await page.goto('/');
  await expect(page.getByLabel('Selected experiment')).toHaveValue(current.id);
  await expect(page.getByTestId('equity-chart')).toBeVisible();
  await page.route(`**/api/v1/experiments/${first.id}`, (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Temporary detail failure' }) }));
  await page.getByLabel('Selected experiment').selectOption(first.id);
  await expect(page.getByRole('alert').filter({ hasText: 'research data' })).toContainText('Temporary detail failure');
  await expect(page.getByTestId('equity-chart')).not.toBeVisible();
  await expect(page.getByRole('link', { name: 'Export', exact: true })).not.toBeVisible();
});
