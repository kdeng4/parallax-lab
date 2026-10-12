import { authConfigured, authServer } from '@/lib/auth-server';
import type { NextRequest } from 'next/server';

async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!authConfigured()) return Response.json({ error: 'Owner Google sign-in is awaiting setup.' },
    { status: 503, headers: { 'Cache-Control': 'no-store' } });
  const handlers = authServer().handler();
  const handler = handlers[request.method as keyof typeof handlers];
  return handler ? handler(request, context) : new Response(null, { status: 405 });
}
export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
