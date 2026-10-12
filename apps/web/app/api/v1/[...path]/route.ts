// This handler runs behind Vercel Authentication for ALL deployed URLs.
// It is the only caller of the private Python service; credentials stay here.
import { editorAccess } from '../../../../lib/editor-access.ts';

export const runtime = 'nodejs';
export const maxDuration = 120;

type Context = { params: Promise<{ path: string[] }> };
const MAX_BODY = 16_384;
const noStore = { 'Cache-Control': 'no-store' };

function fail(detail: string, status: number) {
  return Response.json({ detail }, { status, headers: noStore });
}

async function proxy(request: Request, context: Context) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!/^(health|catalog|market\/overview|experiments(?:\/[0-9a-f-]{36}(?:\/(events|export))?)?)$/.test(route)) {
    return fail('Not found', 404);
  }
  if (request.method === 'POST' && route !== 'experiments') return fail('Method not allowed', 405);

  const hosted = process.env.VERCEL === '1';
  const token = process.env.PARALLAX_API_TOKEN;
  const origin = process.env.BACKEND_INTERNAL_URL ?? (hosted ? undefined : process.env.API_BASE_URL ?? 'http://127.0.0.1:8000');
  if (!origin || (hosted && (!token || token.length < 32))) {
    return fail('Research service is not configured', 503);
  }

  let body: Uint8Array | undefined;
  if (request.method === 'POST') {
    // Platform login cookies must not enable cross-site creation requests.
    const browserOrigin = request.headers.get('origin');
    const host = request.headers.get('host');
    const expectedOrigin = `${hosted ? 'https:' : new URL(request.url).protocol}//${host}`;
    if (browserOrigin && browserOrigin !== expectedOrigin) {
      return fail('Cross-origin request rejected', 403);
    }
    if (request.headers.get('sec-fetch-site') === 'cross-site') return fail('Cross-origin request rejected', 403);
    if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') {
      return fail('Use application/json', 415);
    }
    const access = await editorAccess(request);
    if (!access.canEdit) {
      return fail(access.reason === 'not_configured'
        ? 'Editor authentication is not configured. This workspace is read only.'
        : 'Only approved editors can create experiments.', access.reason === 'not_configured' ? 503 : 403);
    }
    const parts: Uint8Array[] = [];
    let size = 0;
    const reader = request.body?.getReader();
    if (reader) {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BODY) { await reader.cancel(); return fail('Request body is too large', 413); }
        parts.push(value);
      }
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { body.set(part, offset); offset += part.length; }
  }

  try {
    const url = new URL(`/api/v1/${route}`, origin);
    // Market refresh parameters and arbitrary upstream URLs are never accepted.
    url.search = route === 'market/overview' ? '' : new URL(request.url).search;
    const headers = new Headers({ 'Content-Type': 'application/json' });
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const upstream = await fetch(url, {
      method: request.method, headers, body: body as BodyInit | undefined,
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(110_000),
    });
    const outgoing = new Headers({ ...noStore, 'X-Content-Type-Options': 'nosniff' });
    for (const name of ['content-type', 'content-disposition']) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    // Preserve streaming for large exports; do not buffer or set Content-Length.
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return fail('Research service is temporarily unavailable. Please try again.', 502);
  }
}

export const GET = proxy;
export const POST = proxy;
