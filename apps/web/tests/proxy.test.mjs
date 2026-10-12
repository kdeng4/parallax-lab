import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { GET, POST } from '../app/api/v1/[...path]/route.ts';

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
const token = 'test-only-service-token-01234567890123456789';
const context = (path = ['experiments']) => ({ params: Promise.resolve({ path }) });
const request = (options = {}) => new Request('https://lab.example/api/v1/experiments', {
  method: 'POST', body: '{}',
  headers: { host: 'lab.example', origin: 'https://lab.example', 'content-type': 'application/json' },
  ...options,
});

beforeEach(() => {
  process.env.VERCEL = '1';
  process.env.PARALLAX_API_TOKEN = token;
  process.env.BACKEND_INTERNAL_URL = 'https://private-api.example';
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

test('hosted proxy fails closed when service binding or credential is absent', async () => {
  globalThis.fetch = () => assert.fail('must not call upstream');
  delete process.env.BACKEND_INTERNAL_URL;
  assert.equal((await GET(request({ method: 'GET', body: undefined }), context())).status, 503);
  process.env.BACKEND_INTERNAL_URL = 'https://private-api.example';
  delete process.env.PARALLAX_API_TOKEN;
  assert.equal((await POST(request(), context())).status, 503);
});

test('proxy rejects cross-site writes and unexpected routes before contacting the service', async () => {
  globalThis.fetch = () => assert.fail('must not call upstream');
  const headers = { host: 'lab.example', origin: 'https://evil.example', 'content-type': 'application/json' };
  assert.equal((await POST(request({ headers }), context())).status, 403);
  assert.equal((await GET(request(), context(['..', 'secrets']))).status, 404);
  assert.equal((await POST(request(), context(['catalog']))).status, 405);
  assert.equal((await POST(request({ headers: { 'content-type': 'text/plain' } }), context())).status, 415);
  assert.equal((await POST(request({ body: JSON.stringify({ name: 'x'.repeat(20000) }) }), context())).status, 413);
});

test('server credential replaces browser headers and large exports stay streamed', async () => {
  const payload = 'x'.repeat(5_000_000);
  globalThis.fetch = async (url, init) => {
    assert.equal(url.origin, 'https://private-api.example');
    assert.equal(init.headers.get('authorization'), `Bearer ${token}`);
    assert.equal(init.headers.get('cookie'), null);
    assert.equal(init.redirect, 'error');
    return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(payload)); c.close(); } }), {
      headers: { 'content-type': 'application/json', 'content-disposition': 'attachment; filename="test.json"' },
    });
  };
  const result = await GET(request({ method: 'GET', body: undefined, headers: { authorization: 'untrusted', cookie: 'private=1' } }), context());
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('content-length'), null);
  assert.equal(result.headers.get('cache-control'), 'no-store');
  assert.equal(result.headers.get('content-disposition'), 'attachment; filename="test.json"');
  assert.equal((await result.text()).length, payload.length);
});

test('upstream failures never leak private origins or service credentials', async () => {
  globalThis.fetch = async () => { throw new Error(`${token} https://private-api.example`); };
  const result = await POST(request(), context());
  assert.equal(result.status, 502);
  assert.equal((await result.text()).includes(token), false);
});
