import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPair, exportJWK, SignJWT } from 'jose';
import { GET, POST } from '../app/api/v1/[...path]/route.ts';
import { GET as session } from '../app/api/session/route.ts';
import { editorAccess } from '../lib/editor-access.ts';

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
const serviceToken = 'test-only-service-token-01234567890123456789';
const { privateKey, publicKey } = await generateKeyPair('RS256');
const jwk = { ...await exportJWK(publicKey), kid: 'test-key', use: 'sig', alg: 'RS256' };
let issuer, accessToken, upstreamCalls, upstream, sequence = 0;
const context = (path = ['experiments']) => ({ params: Promise.resolve({ path }) });
function request(options = {}, extraHeaders = {}) {
  return new Request('https://lab.example/api/v1/experiments', {
    method: 'POST', body: '{}', ...options,
    headers: { host: 'lab.example', origin: 'https://lab.example', 'content-type': 'application/json',
      'cf-access-jwt-assertion': accessToken, ...extraHeaders },
  });
}
async function signed(overrides = {}, key = privateKey) {
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({ email: 'owner@example.com', type: 'app', sub: 'owner-id',
    iat: now, exp: now + 3600, iss: issuer, aud: ['test-app'], ...overrides })
    .setProtectedHeader({ alg: 'RS256', kid: 'test-key' }).sign(key);
}

beforeEach(async () => {
  issuer = `https://test-${++sequence}.cloudflareaccess.com`;
  process.env.VERCEL = '1';
  process.env.PARALLAX_API_TOKEN = serviceToken;
  process.env.BACKEND_INTERNAL_URL = 'https://private-api.example';
  process.env.PARALLAX_ACCESS_ISSUER = issuer;
  process.env.PARALLAX_ACCESS_AUDIENCE = 'test-app';
  process.env.PARALLAX_EDITOR_EMAILS = 'owner@example.com';
  accessToken = await signed();
  upstreamCalls = 0;
  upstream = async () => Response.json({ id: 'created' }, { status: 201 });
  globalThis.fetch = async (url, init) => {
    if (String(url) === `${issuer}/cdn-cgi/access/certs`) {
      assert.equal(init.headers.get('cookie'), null);
      assert.equal(init.headers.get('authorization'), null);
      return Response.json({ keys: [jwk] });
    }
    upstreamCalls++;
    return upstream(url, init);
  };
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

test('hosted proxy fails closed without service binding, service credential, or editor config', async () => {
  delete process.env.BACKEND_INTERNAL_URL;
  assert.equal((await GET(request({ method: 'GET', body: undefined }), context())).status, 503);
  process.env.BACKEND_INTERNAL_URL = 'https://private-api.example';
  delete process.env.PARALLAX_API_TOKEN;
  assert.equal((await POST(request(), context())).status, 503);
  process.env.PARALLAX_API_TOKEN = serviceToken;
  for (const name of ['PARALLAX_ACCESS_ISSUER', 'PARALLAX_ACCESS_AUDIENCE', 'PARALLAX_EDITOR_EMAILS']) {
    const previous = process.env[name];
    delete process.env[name];
    assert.equal((await POST(request(), context())).status, 503);
    process.env[name] = previous;
  }
  assert.equal(upstreamCalls, 0);
});

test('proxy rejects cross-site writes, wrong media types, large bodies and unexpected routes', async () => {
  assert.equal((await POST(request({}, { origin: 'https://evil.example' }), context())).status, 403);
  assert.equal((await POST(request({}, { 'sec-fetch-site': 'cross-site' }), context())).status, 403);
  assert.equal((await GET(request(), context(['..', 'secrets']))).status, 404);
  assert.equal((await POST(request(), context(['catalog']))).status, 405);
  assert.equal((await POST(request({}, { 'content-type': 'text/plain' }), context())).status, 415);
  assert.equal((await POST(request({ body: JSON.stringify({ name: 'x'.repeat(20000) }) }), context())).status, 413);
  assert.equal(upstreamCalls, 0);
});

test('market reads expose only the fixed overview and cannot force provider refreshes', async () => {
  upstream = async (url, init) => {
    assert.equal(String(url), 'https://private-api.example/api/v1/market/overview');
    assert.equal(init.headers.get('authorization'), `Bearer ${serviceToken}`);
    assert.equal(init.headers.get('cookie'), null);
    return Response.json({ stocks: [] });
  };
  const response = await GET(new Request('https://lab.example/api/v1/market/overview?force=1&url=https://evil.example'), context(['market', 'overview']));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal((await POST(request(), context(['market', 'overview']))).status, 405);
  assert.equal((await GET(new Request('https://lab.example/'), context(['market', 'anything']))).status, 404);
  assert.equal(upstreamCalls, 1);
});

test('anonymous visitors and claimed identity headers cannot create experiments', async () => {
  const result = await POST(request({}, { 'cf-access-jwt-assertion': '',
    'cf-access-authenticated-user-email': 'owner@example.com', 'x-vercel-authenticated-user': 'owner@example.com',
    cookie: 'CF_Authorization=forged', authorization: `Bearer ${serviceToken}` }), context());
  assert.equal(result.status, 403);
  assert.equal(upstreamCalls, 0);
});

for (const [name, claims] of Object.entries({
  'unapproved email': { email: 'visitor@example.com' },
  'wrong audience': { aud: ['different-app'] },
  'wrong issuer': { iss: 'https://other.cloudflareaccess.com' },
  'expired session': { exp: 1 },
  'future session': { nbf: Math.floor(Date.now() / 1000) + 3600 },
  'missing expiry': { exp: undefined },
  'global rather than application token': { type: 'org' },
  'service identity': { common_name: 'service.access', sub: '' },
})) {
  test(`${name} cannot create experiments`, async () => {
    accessToken = await signed(claims);
    assert.equal((await POST(request(), context())).status, 403);
    assert.equal(upstreamCalls, 0);
  });
}

test('forged signature cannot impersonate an approved editor', async () => {
  const attacker = await generateKeyPair('RS256');
  accessToken = await signed({}, attacker.privateKey);
  assert.equal((await POST(request(), context())).status, 403);
  assert.equal(upstreamCalls, 0);
});

test('unavailable identity keys fail closed without leaking errors', async () => {
  globalThis.fetch = async () => { throw new Error('private verification error'); };
  const result = await POST(request(), context());
  assert.equal(result.status, 403);
  assert.equal((await result.text()).includes('private verification error'), false);
  assert.equal(upstreamCalls, 0);
});

test('approved verified editor can create; no browser identity or cookies reach the backend', async () => {
  upstream = async (url, init) => {
    assert.equal(url.origin, 'https://private-api.example');
    assert.equal(init.headers.get('authorization'), `Bearer ${serviceToken}`);
    assert.equal(init.headers.get('cookie'), null);
    assert.equal(init.headers.get('cf-access-jwt-assertion'), null);
    return Response.json({ id: 'created' }, { status: 201 });
  };
  const result = await POST(request({}, { authorization: 'untrusted', cookie: 'private=1' }), context());
  assert.equal(result.status, 201);
  assert.equal(upstreamCalls, 1);
});

test('view-only access preserves streaming large exports', async () => {
  const payload = 'x'.repeat(5_000_000);
  upstream = async (_url, init) => {
    assert.equal(init.redirect, 'error');
    assert.equal(init.headers.get('authorization'), `Bearer ${serviceToken}`);
    return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(payload)); c.close(); } }), {
      headers: { 'content-type': 'application/json', 'content-disposition': 'attachment; filename="test.json"' },
    });
  };
  const result = await GET(request({ method: 'GET', body: undefined }, { 'cf-access-jwt-assertion': '' }), context());
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('content-length'), null);
  assert.equal(result.headers.get('cache-control'), 'no-store');
  assert.equal((await result.text()).length, payload.length);
});

test('upstream failures never leak private origins or service credentials', async () => {
  upstream = async () => { throw new Error(`${serviceToken} https://private-api.example`); };
  const result = await POST(request(), context());
  assert.equal(result.status, 502);
  assert.equal((await result.text()).includes(serviceToken), false);
});

test('session reports verified permission and never caches private identity', async () => {
  let result = await session(request({ method: 'GET', body: undefined }));
  assert.equal(result.headers.get('cache-control'), 'private, no-store');
  assert.deepEqual(await result.json(), { canEdit: true, email: 'owner@example.com', reason: 'approved' });
  accessToken = await signed({ email: 'visitor@example.com' });
  result = await session(request({ method: 'GET', body: undefined }));
  assert.equal((await result.json()).canEdit, false);
});

test('local opt-in cannot bypass authorization on Vercel or a remote hostname', async () => {
  delete process.env.PARALLAX_ACCESS_ISSUER;
  process.env.PARALLAX_LOCAL_WRITE_ACCESS = '1';
  const localRequest = new Request('http://localhost:3000/api/session');
  assert.equal((await editorAccess(localRequest)).canEdit, false);
  delete process.env.VERCEL;
  assert.equal((await editorAccess(localRequest)).canEdit, true);
  assert.equal((await editorAccess(request())).canEdit, false);
  delete process.env.PARALLAX_LOCAL_WRITE_ACCESS;
  assert.equal((await editorAccess(localRequest)).canEdit, false);
});
