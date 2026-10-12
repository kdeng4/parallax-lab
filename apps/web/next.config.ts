import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  async rewrites() {
    const apiBase = (process.env.API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
    if (process.env.VERCEL === '1') {
      const url = URL.canParse(apiBase) ? new URL(apiBase) : null;
      if (!url || url.protocol !== 'https:' || url.origin !== apiBase || url.username || url.password ||
        ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
        throw new Error('Vercel builds require API_BASE_URL to be an HTTPS API origin.');
      }
    }
    return [{ source: '/api/v1/:path*', destination: `${apiBase}/api/v1/:path*` }];
  },
};

export default nextConfig;
