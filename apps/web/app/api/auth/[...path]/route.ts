import { authConfigured, authServer } from '@/lib/auth-server';
import type { NextRequest } from 'next/server';
import { allowedAuthRequest } from '@/lib/auth-policy';

async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!await allowedAuthRequest(request, (await context.params).path))
    return Response.json({ error: 'Only owner GitHub sign-in is supported.' }, { status: 403, headers: { 'Cache-Control': 'no-store' } });
  if (!authConfigured()) return Response.json({ error: 'Owner GitHub sign-in is awaiting setup.' },
    { status: 503, headers: { 'Cache-Control': 'no-store' } });
  const handlers = authServer().handler();
  const handler = handlers[request.method as keyof typeof handlers];
  return handler ? handler(request, context) : new Response(null, { status: 405 });
}
export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
