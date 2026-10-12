import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test from 'node:test';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';

test('native Workers runtime syncs a KV plan and rejects upstream redirects without forwarding credentials', async () => {
  let redirect = false;
  const requests: string[] = [];
  const secret = 'native-runtime-test-only-01234567890123456789';
  const backend = createServer((request, response) => {
    requests.push(request.url ?? '');
    assert.equal(request.headers.authorization, `Bearer ${secret}`);
    if (redirect) {
      response.writeHead(302, { Location: '/redirect-target' }); response.end();
    } else {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ studies: [{ id: '00000000-0000-4000-8000-000000000000', windows: [] }] }));
    }
  });
  await new Promise<void>(resolve => backend.listen(0, '127.0.0.1', resolve));
  const address = backend.address();
  assert.ok(address && typeof address !== 'string');
  const worker = new Miniflare(convertV4MiniflareOptions({
    modules: true, scriptPath: 'dist/index.js', compatibilityDate: '2026-10-12', compatibilityFlags: ['nodejs_compat'],
    kvNamespaces: ['PLAN'], bindings: { SCHEDULER_TOKEN: secret, BACKEND_ORIGIN: `http://127.0.0.1:${address.port}` },
  }));
  try {
    await worker.ready;
    const headers = { Authorization: `Bearer ${secret}` };
    const result = await worker.dispatchFetch('https://scheduler.example/sync', { method: 'POST', headers });
    assert.equal(result.status, 200);
    assert.deepEqual(await result.json(), { synced: true, active_studies: 1 });
    const kv = await worker.getKVNamespace('PLAN');
    const plan = await kv.get('plan', 'json');
    assert.equal(plan.studies.length, 1);
    redirect = true;
    const rejected = await worker.dispatchFetch('https://scheduler.example/sync', { method: 'POST', headers });
    assert.equal(rejected.status, 503);
    assert.deepEqual(await rejected.json(), { synced: false, reason: 'plan_http_302' });
    assert.deepEqual(requests, ['/api/scheduler/plan', '/api/scheduler/plan']);
    const retained = await kv.get('plan', 'json');
    assert.deepEqual(retained, plan);
  } finally {
    await worker.dispose();
    await new Promise<void>((resolve, reject) => backend.close(error => error ? reject(error) : resolve()));
  }
});
