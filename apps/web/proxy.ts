import { NextRequest, NextResponse } from 'next/server';
import { authConfigured, authServer } from './lib/auth-server';

export default async function proxy(request: NextRequest) {
  if (process.env.VERCEL !== '1' && process.env.PARALLAX_LOCAL_WRITE_ACCESS === '1'
    && ['localhost', '127.0.0.1', '[::1]'].includes(request.nextUrl.hostname)) return NextResponse.next();
  if (!authConfigured()) return NextResponse.redirect(new URL('/auth/sign-in', request.url));
  return authServer().middleware({ loginUrl: '/auth/sign-in' })(request);
}

export const config = { matcher: ['/workspace/:path*'] };
