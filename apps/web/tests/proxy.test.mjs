import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { GET, POST } from '../app/api/v1/[...path]/route.ts';
import { GET as publicDashboard } from '../app/api/public/dashboard/route.ts';
import { GET as sessionRoute } from '../app/api/session/route.ts';
import { authorizeGitHub, editorAccess } from '../lib/editor-access.ts';
import { allowedAuthRequest } from '../lib/auth-policy.ts';

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
  process.env.PARALLAX_OWNER_GITHUB_ID = '49372435';
  delete process.env.NEON_AUTH_GITHUB_READY;
  calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return Response.json({ ok: true }); };
});
afterEach(() => { process.env = { ...oldEnv }; globalThis.fetch = oldFetch; });

for (const path of ['health', 'catalog', 'market/overview', 'market/watchlist', 'context/overview', 'experiments',
  'experiments/00000000-0000-4000-8000-000000000000', 'experiments/00000000-0000-4000-8000-000000000000/events',
  'experiments/00000000-0000-4000-8000-000000000000/export']) {
  test(`private ${path} fails closed without a GitHub session`, async () => {
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

test('watchlist writes require the same owner and CSRF checks as experiments', async () => {
  const path = 'market/watchlist';
  const body = JSON.stringify({ symbols: ['TSLA', 'AMD'] });
  assert.equal((await POST(request(path, 'POST', {}, body), context(path))).status, 503);
  assert.equal(calls.length, 0);
  local();
  assert.equal((await POST(request(path, 'POST', { origin: 'https://evil.example' }, body), context(path))).status, 403);
  assert.equal(calls.length, 0);
  const response = await POST(request(path, 'POST', {}, body), context(path));
  assert.equal(response.status, 200);
  assert.equal(calls[0].url, 'https://private.example/api/v1/market/watchlist');
  assert.equal(calls[0].init.headers.get('authorization'), `Bearer ${token}`);
});
const verified = email => ({ user: { email, emailVerified: true }, session: { expiresAt: new Date(Date.now() + 3600000) } });
const owner = [{ providerId: 'github', accountId: '49372435' }];
test('only the immutable GitHub owner ID grants private reads and writes', () => {
  const access = authorizeGitHub(verified('owner@example.com'), owner, '49372435');
  assert.equal(access.canView, true); assert.equal(access.canEdit, true);
  // Matching email, a recycled username, or legacy viewer configuration cannot grant access.
  process.env.PARALLAX_VIEWER_EMAILS = 'owner@example.com';
  const other = authorizeGitHub(verified('owner@example.com'), [{ providerId: 'github', accountId: '12345' }], '49372435');
  assert.equal(other.canView, false); assert.equal(other.canEdit, false);
});
test('private email and a changed email do not lock out the same GitHub identity', () => {
  for (const email of [null, 'changed@example.com'])
    assert.equal(authorizeGitHub(verified(email), owner, '49372435').canEdit, true);
});
test('expired, missing and non-GitHub identities are denied', () => {
  for (const session of [null, { user: {}, session: {} },
    { ...verified('owner@example.com'), session: { expiresAt: '2000-01-01' } },
    { ...verified('owner@example.com'), session: { expiresAt: 'invalid' } }])
    assert.equal(authorizeGitHub(session, owner, '49372435').canView, false);
  for (const providerId of ['google', 'credential'])
    assert.equal(authorizeGitHub(verified('owner@example.com'), [{ providerId, accountId: '49372435' }], '49372435').canEdit, false);
  assert.equal(authorizeGitHub(verified('owner@example.com'), [{ providerId: 'github' }], '49372435').canEdit, false);
});
test('owner setting accepts one numeric ID, never a username, email or list', () => {
  for (const id of ['', 'kdeng4', 'owner@example.com', '49372435,12345', '049372435'])
    assert.equal(authorizeGitHub(verified('owner@example.com'), owner, id).reason, 'not_configured');
});
test('legacy Google settings cannot activate GitHub authorization', async () => {
  process.env.NEON_AUTH_BASE_URL = 'https://auth.example';
  process.env.NEON_AUTH_COOKIE_SECRET = 'x'.repeat(40);
  process.env.NEON_AUTH_GOOGLE_READY = '1';
  process.env.PARALLAX_EDITOR_EMAILS = 'owner@example.com';
  assert.equal((await editorAccess(request())).reason, 'not_configured');
});
test('auth proxy permits GitHub identity login and rejects alternate providers or expanded scopes', async () => {
  const social = body => request('unused', 'POST', {}, JSON.stringify(body));
  assert.equal(await allowedAuthRequest(social({ provider: 'github', callbackURL: '/workspace' }), ['sign-in', 'social']), true);
  for (const body of [{ provider: 'google' }, { provider: 'github', scopes: ['repo'] },
    { provider: 'github', additionalParams: { scope: 'repo' } }])
    assert.equal(await allowedAuthRequest(social(body), ['sign-in', 'social']), false);
  assert.equal(await allowedAuthRequest(request('unused', 'POST', {}, '{'), ['sign-in', 'social']), false);
  assert.equal(await allowedAuthRequest(social({ provider: 'google' }), ['sign-in/social']), false);
});
test('auth proxy rejects password, email signup and account linking while preserving session endpoints', async () => {
  for (const path of ['sign-up/email', 'sign-in/email', 'sign-in/email-otp', 'link-social', 'set-password', 'change-email'])
    assert.equal(await allowedAuthRequest(request('unused', 'POST', {}, '{}'), path.split('/')), false);
  assert.equal(await allowedAuthRequest(request('unused', 'POST', {}, '{}'), ['sign-up/email']), false);
  for (const path of ['get-session', 'sign-out', 'list-accounts', 'callback/github'])
    assert.equal(await allowedAuthRequest(request(), path.split('/')), true);
});
test('session endpoint is private-cache only and grants no rights when unconfigured', async () => {
  const response = await sessionRoute(request());
  assert.equal((await response.json()).canEdit, false);
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
});
