import { timingSafeEqual } from 'node:crypto';

type SessionWindow = { start: number; end: number };
type Study = { id: string; windows: SessionWindow[] };
type Plan = { fetched_at: number; studies: Study[] };
const headers = { 'Cache-Control': 'no-store', 'Content-Type': 'application/json' };

export function inWindow(study: Study, now: Date): boolean {
  return study.windows.some(window => window.start <= now.getTime() && now.getTime() < window.end);
}

function authorized(request: Request, env: Env): boolean {
  if (!env.SCHEDULER_TOKEN || env.SCHEDULER_TOKEN.length < 32) return false;
  const encoder = new TextEncoder();
  const expected = encoder.encode(`Bearer ${env.SCHEDULER_TOKEN}`);
  const supplied = encoder.encode(request.headers.get('authorization') ?? '');
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

async function boundedJSON(response: Response): Promise<unknown> {
  if (!response.ok) throw new Error(`plan_http_${response.status}`);
  if (!response.body) throw new Error('plan_body_missing');
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 32_768) { await reader.cancel(); throw new Error('Scheduler plan too large'); }
    parts.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { body.set(part, offset); offset += part.length; }
  try { return JSON.parse(new TextDecoder().decode(body)); }
  catch { throw new Error('plan_invalid_json'); }
}

export async function refreshPlan(env: Env): Promise<Plan> {
  if (!env.SCHEDULER_TOKEN || env.SCHEDULER_TOKEN.length < 32) throw new Error('Scheduler is not configured');
  let response: Response;
  try {
    response = await fetch(new URL('/api/scheduler/plan', env.BACKEND_ORIGIN), {
      headers: { Authorization: `Bearer ${env.SCHEDULER_TOKEN}` }, redirect: 'manual', signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    console.error('plan_fetch_failed', { type: error instanceof Error ? error.name : 'unknown' });
    throw new Error('plan_request_failed');
  }
  const value = await boundedJSON(response) as { studies?: unknown };
  if (!Array.isArray(value?.studies) || value.studies.length > 2) throw new Error('Invalid scheduler plan');
  const studies: Study[] = value.studies.map(item => {
    if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !/^[0-9a-f-]{36}$/.test(item.id)
        || !Array.isArray(item.windows) || item.windows.length > 2) throw new Error('Invalid study schedule');
    const windows = (item.windows as unknown[]).map(value => {
      if (!value || typeof value !== 'object') throw new Error('Invalid market session windows');
      const window = value as Partial<SessionWindow>;
      if (typeof window.start !== 'number' || typeof window.end !== 'number'
        || !Number.isSafeInteger(window.start) || !Number.isSafeInteger(window.end) || window.start >= window.end
        || window.end - window.start > 10_800_000) throw new Error('Invalid market session windows');
      return { start: window.start, end: window.end };
    });
    // The backend applies the exchange calendar and timezone. Only UTC intervals
    // are retained, keeping minute invocations below the Free CPU allowance.
    return { id: item.id, windows };
  });
  const plan = { fetched_at: Date.now(), studies };
  try { await env.PLAN.put('plan', JSON.stringify(plan)); }
  catch { throw new Error('plan_cache_write_failed'); }
  return plan;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET')
      return new Response(JSON.stringify({ status: 'ok', configured: Boolean(env.SCHEDULER_TOKEN && env.SCHEDULER_TOKEN.length >= 32) }), { headers });
    if (url.pathname !== '/sync') return new Response('Not found', { status: 404 });
    if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
    if (!authorized(request, env)) return new Response('Authentication required', { status: 401, headers });
    if (url.search) return new Response('Query parameters are not accepted', { status: 400 });
    try {
      const plan = await refreshPlan(env);
      return new Response(JSON.stringify({ synced: true, active_studies: plan.studies.length }), { headers });
    } catch (error) {
      const reason = error instanceof Error && /^plan_[a-z0-9_]+$/.test(error.message) ? error.message : 'plan_sync_failed';
      console.error('scheduler_sync_failed', { reason });
      return new Response(JSON.stringify({ synced: false, reason }), { status: 503, headers });
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
