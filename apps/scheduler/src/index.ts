import { timingSafeEqual } from 'node:crypto';

type SessionWindow = { start: number; end: number };
type Study = { id: string; windows: SessionWindow[] };
type Plan = { fetched_at: number; studies: Study[] };
const headers = { 'Cache-Control': 'no-store', 'Content-Type': 'application/json' };
const maxPlanBytes = 32_768;

function configured(env: Env): boolean {
  return Boolean(env.SCHEDULER_TOKEN && env.SCHEDULER_TOKEN.length >= 32);
}

export function inWindow(study: Study, now: Date): boolean {
  const timestamp = now.getTime();
  return study.windows.some(window => window.start <= timestamp && timestamp < window.end);
}

async function authorized(request: Request, env: Env): Promise<boolean> {
  if (!configured(env)) return false;
  const encoder = new TextEncoder();
  const [supplied, expected] = await Promise.all([
    crypto.subtle.digest('SHA-256', encoder.encode(request.headers.get('authorization') ?? '')),
    crypto.subtle.digest('SHA-256', encoder.encode(`Bearer ${env.SCHEDULER_TOKEN}`)),
  ]);
  return timingSafeEqual(new Uint8Array(supplied), new Uint8Array(expected));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function parseWindow(value: unknown): SessionWindow {
  if (!isRecord(value)) throw new Error('Invalid market session windows');
  const { start, end } = value;
  if (typeof start !== 'number' || typeof end !== 'number'
    || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start >= end
    || end - start > 10_800_000) throw new Error('Invalid market session windows');
  return { start, end };
}

function parseStudy(value: unknown): Study {
  if (!isRecord(value) || typeof value.id !== 'string' || !/^[0-9a-f-]{36}$/.test(value.id)
      || !Array.isArray(value.windows) || value.windows.length > 2) throw new Error('Invalid study schedule');
  // The backend applies the exchange calendar and timezone. Only UTC intervals
  // are retained, keeping minute invocations below the Free CPU allowance.
  return { id: value.id, windows: value.windows.map(parseWindow) };
}

function parseStudies(value: unknown): Study[] {
  if (!isRecord(value) || !Array.isArray(value.studies) || value.studies.length > 2)
    throw new Error('Invalid scheduler plan');
  return value.studies.map(parseStudy);
}

async function boundedJSON(response: Response): Promise<unknown> {
  if (!response.ok) throw new Error(`plan_http_${response.status}`);
  if (!response.body) throw new Error('plan_body_missing');
  const reader = response.body.getReader();
  const body = new Uint8Array(maxPlanBytes);
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    if (size + value.byteLength > body.byteLength) {
      await reader.cancel();
      throw new Error('Scheduler plan too large');
    }
    body.set(value, size);
    size += value.byteLength;
  }
  try { return JSON.parse(new TextDecoder().decode(body.subarray(0, size))); }
  catch { throw new Error('plan_invalid_json'); }
}

export async function refreshPlan(env: Env): Promise<Plan> {
  if (!configured(env)) throw new Error('Scheduler is not configured');
  let response: Response;
  try {
    response = await fetch(new URL('/api/scheduler/plan', env.BACKEND_ORIGIN), {
      headers: { Authorization: `Bearer ${env.SCHEDULER_TOKEN}` }, redirect: 'manual', signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    console.error(JSON.stringify({ message: 'plan_fetch_failed', type: error instanceof Error ? error.name : 'unknown' }));
    throw new Error('plan_request_failed');
  }
  const studies = parseStudies(await boundedJSON(response));
  const plan = { fetched_at: Date.now(), studies };
  try { await env.PLAN.put('plan', JSON.stringify(plan)); }
  catch { throw new Error('plan_cache_write_failed'); }
  return plan;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET')
      return Response.json({ status: 'ok', configured: configured(env) }, { headers });
    if (url.pathname !== '/sync') return new Response('Not found', { status: 404 });
    if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
    if (!(await authorized(request, env))) return new Response('Authentication required', { status: 401, headers });
    if (url.search) return new Response('Query parameters are not accepted', { status: 400 });
    try {
      const plan = await refreshPlan(env);
      return Response.json({ synced: true, active_studies: plan.studies.length }, { headers });
    } catch (error) {
      const reason = error instanceof Error && /^plan_[a-z0-9_]+$/.test(error.message) ? error.message : 'plan_sync_failed';
      console.error(JSON.stringify({ message: 'scheduler_sync_failed', reason }));
      return Response.json({ synced: false, reason }, { status: 503, headers });
    }
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    let plan = await env.PLAN.get<Plan>('plan', 'json');
    // Outside active windows only KV is read. Hourly refresh provides recovery
    // if an owner's immediate /sync failed, without waking Postgres every minute.
    if (!plan || controller.scheduledTime - plan.fetched_at >= 3_600_000) plan = await refreshPlan(env);
    if (!plan.studies.some(study => inWindow(study, new Date(controller.scheduledTime)))) return;
    const response = await fetch(new URL('/api/scheduler/tick', env.BACKEND_ORIGIN), {
      method: 'POST', headers: { Authorization: `Bearer ${env.SCHEDULER_TOKEN}`, 'Content-Type': 'application/json' },
      body: '{}', redirect: 'manual', signal: AbortSignal.timeout(110_000),
    });
    const ok = response.ok;
    await response.body?.cancel();
    if (!ok) throw new Error('Scheduler tick unavailable');
  },
} satisfies ExportedHandler<Env>;
