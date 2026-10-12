import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { GET, POST } from '../app/api/v1/[...path]/route.ts';
import { GET as publicDashboard } from '../app/api/public/dashboard/route.ts';
import { GET as sessionRoute } from '../app/api/session/route.ts';
import { authorizeGoogle, editorAccess } from '../lib/editor-access.ts';

const oldFetch = globalThis.fetch;
const oldEnv = { ...process.env };
const token = 'test-only-service-token-01234567890123456789';
let calls;
const context = path => ({ params: Promise.resolve({ path: path.split('/') }) });
function request(path = 'experiments', method = 'GET', headers = {}, body) {
  return new Request(`http://localhost/api/v1/${path}`, { method, headers: { host: 'localhost', origin: 'http://localhost', 'content-type': 'application/json', ...headers }, body });
}
function local() { delete process.env.VERCEL; process.env.PARALLAX_LOCAL_WRITE_ACCESS = '1'; }
beforeEach(() => {
  process.env.VERCEL = '1'; process.env.PARALLAX_API_TOKEN = token;
  process.env.BACKEND_INTERNAL_URL = 'https://private.example';
  process.env.PARALLAX_EDITOR_EMAILS = 'owner@example.com';
  delete process.env.NEON_AUTH_GOOGLE_READY;
  calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return Response.json({ ok: true }); };
});
afterEach(() => { process.env = { ...oldEnv }; globalThis.fetch = oldFetch; });

for (const path of ['health', 'catalog', 'market/overview', 'context/overview', 'experiments',
  'experiments/00000000-0000-4000-8000-000000000000', 'experiments/00000000-0000-4000-8000-000000000000/events',
  'experiments/00000000-0000-4000-8000-000000000000/export']) {
  test(`private ${path} fails closed without a Google session`, async () => {
    const response = await GET(request(path, 'GET', { authorization: `Bearer ${token}`, cookie: 'forged=1',
      'cf-access-jwt-assertion': 'forged', 'x-vercel-authenticated-user': 'owner@example.com' }), context(path));
    assert.equal(response.status, 503); assert.equal(calls.length, 0);
  });
}
test('missing service binding and credentials fail closed', async () => {
  delete process.env.BACKEND_INTERNAL_URL;
  assert.equal((await GET(request(), context('experiments'))).status, 503);
  assert.equal(calls.length, 0);
});
test('hosted localhost headers cannot enable the development bypass', async () => {
  process.env.PARALLAX_LOCAL_WRITE_ACCESS = '1';
  assert.equal((await editorAccess(request())).canView, false);
  assert.equal((await POST(request('experiments', 'POST', {}, '{}'), context('experiments'))).status, 503);
});
test('public endpoint uses only the dedicated projection and never forwards visitor headers or queries', async () => {
  const response = await publicDashboard();
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://private.example/api/v1/public/dashboard');
  assert.deepEqual(calls[0].init.headers, { Authorization: `Bearer ${token}` });
  assert.equal(response.headers.get('cache-control'), 'no-store');
});
test('public upstream failures return no backend details', async () => {
  globalThis.fetch = async () => { throw new Error('sensitive upstream details'); };
  const response = await publicDashboard();
  assert.equal(response.status, 503);
  assert.equal((await response.text()).includes('sensitive'), false);
});
test('arbitrary routes and public aliases are not private proxy escape hatches', async () => {
  local();
  for (const path of ['../secrets', 'public/dashboard', 'market/anything', 'context/anything'])
    assert.equal((await GET(request(), context(path))).status, 404);
  assert.equal((await POST(request('catalog', 'POST', {}, '{}'), context('catalog'))).status, 405);
  assert.equal(calls.length, 0);
});
test('approved local reads strip refresh and upstream URL parameters', async () => {
  local();
  for (const path of ['market/overview', 'context/overview']) {
    const response = await GET(request(`${path}?force=1&url=https://evil.example`), context(path));
    assert.equal(response.status, 200);
    assert.equal(calls.at(-1).url, `https://private.example/api/v1/${path}`);
    assert.equal(calls.at(-1).init.headers.get('cookie'), null);
  }
});
test('authorized writes still reject CSRF, incorrect media types and oversized bodies', async () => {
  local();
  for (const [headers, body, expected] of [[{ origin: 'https://evil.example' }, '{}', 403],
    [{ 'sec-fetch-site': 'cross-site' }, '{}', 403], [{ 'content-type': 'text/plain' }, '{}', 415], [{}, 'x'.repeat(20000), 413]]) {
    assert.equal((await POST(request('experiments', 'POST', headers, body), context('experiments'))).status, expected);
  }
  assert.equal(calls.length, 0);
});
test('approved local write streams the response and keeps the service key server-side', async () => {
  local(); const response = await POST(request('experiments', 'POST', {}, '{}'), context('experiments'));
  assert.equal(response.status, 200);
  assert.equal(calls[0].init.headers.get('authorization'), `Bearer ${token}`);
  assert.equal((await response.text()).includes(token), false);
});
const verified = email => ({ user: { email, emailVerified: true }, session: { expiresAt: new Date(Date.now() + 3600000) } });
test('only the allowlisted verified Google owner can edit', () => {
  assert.equal(authorizeGoogle(verified('OWNER@example.com'), [{ providerId: 'google' }], 'owner@example.com').canEdit, true);
  assert.equal(authorizeGoogle(verified('other@example.com'), [{ providerId: 'google' }], 'owner@example.com').canView, false);
});
test('explicitly approved viewers can read but cannot edit', () => {
  const access = authorizeGoogle(verified('viewer@example.com'), [{ providerId: 'google' }], 'owner@example.com', 'viewer@example.com');
  assert.equal(access.canView, true); assert.equal(access.canEdit, false);
});
test('unverified, expired, missing and non-Google identities are denied', () => {
  for (const session of [null, { ...verified('owner@example.com'), user: { email: 'owner@example.com', emailVerified: false } },
    { ...verified('owner@example.com'), session: { expiresAt: '2000-01-01' } },
    { ...verified('owner@example.com'), session: { expiresAt: 'invalid' } }])
    assert.equal(authorizeGoogle(session, [{ providerId: 'google' }], 'owner@example.com').canView, false);
  assert.equal(authorizeGoogle(verified('owner@example.com'), [{ providerId: 'credential' }], 'owner@example.com').canEdit, false);
});
test('session endpoint is private-cache only and grants no rights when unconfigured', async () => {
  const response = await sessionRoute(request());
  assert.equal((await response.json()).canEdit, false);
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
});
