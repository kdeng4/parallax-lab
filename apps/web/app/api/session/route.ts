import { editorAccess } from '../../../lib/editor-access.ts';

export const runtime = 'nodejs';

export async function GET(request: Request) {
  return Response.json(await editorAccess(request), {
    headers: { 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff' },
  });
}
