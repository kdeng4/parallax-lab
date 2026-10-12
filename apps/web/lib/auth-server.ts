import { createNeonAuth } from '@neondatabase/auth/next/server';

export function authConfigured() {
  return Boolean(process.env.NEON_AUTH_BASE_URL?.startsWith('https://')
    && (process.env.NEON_AUTH_COOKIE_SECRET?.length ?? 0) >= 32
    && process.env.NEON_AUTH_GITHUB_READY === '1'
    && /^[1-9]\d*$/.test(process.env.PARALLAX_OWNER_GITHUB_ID ?? ''));
}

export function authServer() {
  if (!authConfigured()) throw new Error('Owner sign-in is awaiting configuration');
  return createNeonAuth({ baseUrl: process.env.NEON_AUTH_BASE_URL!,
    cookies: { secret: process.env.NEON_AUTH_COOKIE_SECRET!, sessionDataTtl: 60 } });
}
