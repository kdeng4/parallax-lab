import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import worker, { inWindow, refreshPlan } from '../src/index.ts';

const oldFetch = globalThis.fetch;
const study = { id: '00000000-0000-4000-8000-000000000000', timezone: 'America/Toronto', window_start: '09:45', window_end: '10:45', windows: [
  { start: Date.parse('2026-10-12T13:45:00Z'), end: Date.parse('2026-10-12T14:45:00Z') },
  { start: Date.parse('2026-11-02T14:45:00Z'), end: Date.parse('2026-11-02T15:45:00Z') },
] };
let calls: { url: string; init: RequestInit | undefined }[];
let cached: unknown;
let puts: number;
const env = () => ({ SCHEDULER_TOKEN: 'unit-test-secret-012345678901234567890', BACKEND_ORIGIN: 'https://parallax.pdeng.pp.ua',
  PLAN: { get: async () => cached, put: async (_key: string, value: string) => { cached = JSON.parse(value); puts++; } } });
const run = (now: number) => worker.scheduled({ scheduledTime: now, cron: '* * * * *' }, env());
beforeEach(() => {
  calls = []; cached = null; puts = 0;
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return Response.json({ studies: [] }); };
});
afterEach(() => { globalThis.fetch = oldFetch; });

test('windows follow timezone/DST and exclude weekends and the end boundary', () => {
  assert.equal(inWindow(study, new Date('2026-10-12T14:00:00Z')), true);
  assert.equal(inWindow(study, new Date('2026-11-02T15:00:00Z')), true);
  assert.equal(inWindow(study, new Date('2026-10-10T14:00:00Z')), false);
  assert.equal(inWindow(study, new Date('2026-10-12T14:45:00Z')), false);
  assert.equal(inWindow(study, new Date('2026-10-12T13:44:00Z')), false);
});
test('outside windows and with no studies, cron makes no backend requests', async () => {
  const now = Date.parse('2026-10-12T12:00:00Z');
  cached = { fetched_at: now, studies: [study] };
  await run(now); assert.equal(calls.length, 0);
  cached = { fetched_at: now, studies: [] };
  await run(now); assert.equal(calls.length, 0); assert.equal(puts, 0);
});
test('hourly fallback refreshes once, so idle cron does not wake the database every minute', async () => {
  const now = Date.now();
  await run(now);
  assert.equal(calls.length, 1); assert.equal(puts, 1);
  await run(now + 60_000); assert.equal(calls.length, 1);
  await run(cached.fetched_at + 3_600_001); assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'https://parallax.pdeng.pp.ua/api/scheduler/plan');
  assert.equal(calls[0].init?.redirect, 'error');
});
test('active window sends only authenticated tick with an empty body', async () => {
  const now = Date.parse('2026-10-12T14:00:00Z');
  cached = { fetched_at: now, studies: [study] };
  await run(now);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://parallax.pdeng.pp.ua/api/scheduler/tick');
  assert.equal(calls[0].init?.method, 'POST'); assert.equal(calls[0].init?.body, '{}');
  assert.equal(calls[0].init?.headers.Authorization, `Bearer ${env().SCHEDULER_TOKEN}`);
  assert.equal(calls[0].init?.redirect, 'error');
});
test('health leaks no schedule/secret and sync cannot be called by a visitor', async () => {
  const health = await worker.fetch(new Request('https://scheduler.example/health'), env());
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: 'ok', configured: true });
  for (const supplied of ['', 'Bearer wrong', `Bearer ${env().SCHEDULER_TOKEN.slice(0, -1)}X`]) {
    const response = await worker.fetch(new Request('https://scheduler.example/sync', { method: 'POST', headers: { Authorization: supplied } }), env());
    assert.equal(response.status, 401);
  }
  assert.equal(calls.length, 0);
  assert.equal((await worker.fetch(new Request('https://scheduler.example/sync'), env())).status, 405);
  assert.equal((await worker.fetch(new Request('https://scheduler.example/nope'), env())).status, 404);
});
test('authenticated sync refreshes a bounded validated schedule, without triggering market data or model calls', async () => {
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return Response.json({ studies: [study] }); };
  const request = new Request('https://scheduler.example/sync', { method: 'POST', headers: { Authorization: `Bearer ${env().SCHEDULER_TOKEN}` } });
  const response = await worker.fetch(request, env());
  assert.equal(response.status, 200); assert.equal(calls.length, 1);
  assert.deepEqual(await response.json(), { synced: true, active_studies: 1 });
  assert.equal(cached.studies[0].windows[0].start, study.windows[0].start);
  assert.equal(cached.studies[0].timezone, undefined);
  assert.equal((await worker.fetch(new Request('https://scheduler.example/sync?force=1', { method: 'POST', headers: request.headers }), env())).status, 400);
});
test('invalid plans and excessive transfer are rejected without persisting content', async () => {
  for (const body of [{ studies: [study, study, study] }, { studies: [{ ...study, windows: [{ start: 'wrong', end: 1 }] }] },
    { studies: [{ ...study, id: '../private' }] }, { studies: [{ ...study, windows: [{ start: 2, end: 1 }] }] }, {}, { studies: 'bad' }]) {
    globalThis.fetch = async () => Response.json(body);
    await assert.rejects(refreshPlan(env()));
  }
  globalThis.fetch = async () => new Response('x'.repeat(32769));
  await assert.rejects(refreshPlan(env()), /too large/);
  assert.equal(puts, 0);
  await assert.rejects(refreshPlan({ ...env(), SCHEDULER_TOKEN: '' }), /not configured/);
});
test('backend failures are sanitized and are not automatically retried within the invocation', async () => {
  globalThis.fetch = async () => new Response('sensitive upstream error', { status: 500 });
  const response = await worker.fetch(new Request('https://scheduler.example/sync', { method: 'POST', headers: { Authorization: `Bearer ${env().SCHEDULER_TOKEN}` } }), env());
  assert.equal(response.status, 503); assert.equal((await response.text()).includes('sensitive'), false);
  const now = Date.parse('2026-10-12T14:00:00Z');
  cached = { fetched_at: now, studies: [study] };
  await assert.rejects(run(now), /tick unavailable/);
});
