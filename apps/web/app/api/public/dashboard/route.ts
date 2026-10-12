export const runtime = 'nodejs';

export async function GET() {
  const hosted = process.env.VERCEL === '1';
  const origin = process.env.BACKEND_INTERNAL_URL ?? (hosted ? undefined : process.env.API_BASE_URL ?? 'http://127.0.0.1:8000');
  const token = process.env.PARALLAX_API_TOKEN;
  const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
  if (!origin || (hosted && (!token || token.length < 32))) return Response.json({ error: 'Dashboard unavailable' }, { status: 503, headers });
  try {
    const response = await fetch(new URL('/api/v1/public/dashboard', origin), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error('Unavailable');
    return Response.json(await response.json(), { headers });
  } catch { return Response.json({ error: 'Dashboard unavailable' }, { status: 503, headers }); }
}
