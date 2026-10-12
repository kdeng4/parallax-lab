// Machine-only bridge. It never accepts a browser session or forwards visitor headers.
import { timingSafeEqual } from 'node:crypto';

export const runtime = 'nodejs';
export const maxDuration = 120;
type Context = { params: Promise<{ action: string }> };
const noStore = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const fail = (detail: string, status: number) => Response.json({ detail }, { status, headers: noStore });

async function bridge(request: Request, context: Context) {
  const { action } = await context.params;
  if (!['plan', 'tick'].includes(action)) return fail('Not found', 404);
  if (request.method !== (action === 'plan' ? 'GET' : 'POST')) return fail('Method not allowed', 405);
  const secret = process.env.PARALLAX_SCHEDULER_TOKEN;
  if (!secret || secret.length < 32) return fail('Scheduler is not configured', 503);
  const expected = Buffer.from(`Bearer ${secret}`);
  const supplied = Buffer.from(request.headers.get('authorization') ?? '');
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return fail('Authentication required', 401);
  if (new URL(request.url).search) return fail('Query parameters are not accepted', 400);
  if (request.method === 'POST') {
    if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') return fail('Use application/json', 415);
    let size = 0;
    const reader = request.body?.getReader();
    if (reader) for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 1024) { await reader.cancel(); return fail('Request body is too large', 413); }
    }
  }
  const origin = process.env.BACKEND_INTERNAL_URL;
  const token = process.env.PARALLAX_API_TOKEN;
  if (!origin || !token || token.length < 32) return fail('Research service is not configured', 503);
  try {
    const response = await fetch(new URL(`/api/v1/scheduler/${action}`, origin), {
      method: request.method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(request.method === 'POST' ? { body: '{}' } : {}), cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(110_000),
    });
    if (!response.ok) return fail('Scheduler backend is unavailable', 502);
    return new Response(response.body, { status: 200, headers: { ...noStore, 'Content-Type': 'application/json' } });
  } catch { return fail('Scheduler backend is unavailable', 502); }
}
export const GET = bridge;
export const POST = bridge;
