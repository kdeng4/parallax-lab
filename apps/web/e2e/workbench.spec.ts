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
