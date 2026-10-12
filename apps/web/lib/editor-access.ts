import { createRemoteJWKSet, customFetch, jwtVerify } from 'jose';

export type EditorAccess = {
  canEdit: boolean;
  email: string | null;
  reason: 'approved' | 'local' | 'sign_in' | 'not_approved' | 'not_configured';
};

let cachedIssuer = '';
let keys: ReturnType<typeof createRemoteJWKSet> | undefined;

/** Only a verified, application-scoped Cloudflare Access identity can write. */
export async function editorAccess(request: Request): Promise<EditorAccess> {
  const issuer = process.env.PARALLAX_ACCESS_ISSUER ?? '';
  const audience = process.env.PARALLAX_ACCESS_AUDIENCE ?? '';
  const editors = (process.env.PARALLAX_EDITOR_EMAILS ?? '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean);

  // Explicit opt-in for the localhost development runner, never honored on Vercel.
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(new URL(request.url).hostname);
  if (process.env.VERCEL !== '1' && !issuer && local && process.env.PARALLAX_LOCAL_WRITE_ACCESS === '1') {
    return { canEdit: true, email: null, reason: 'local' };
  }
  if (!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer) || !audience || !editors.length) {
    return { canEdit: false, email: null, reason: 'not_configured' };
  }

  const token = request.headers.get('cf-access-jwt-assertion');
  if (!token || token.length > 16_384) return { canEdit: false, email: null, reason: 'sign_in' };
  try {
    if (!keys || cachedIssuer !== issuer) {
      keys = createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`), {
        timeoutDuration: 5_000,
        // Public signing keys only. Browser credentials are never sent to this endpoint.
        [customFetch]: (url, options) => fetch(url, { ...options, cache: 'no-store' }),
      });
      cachedIssuer = issuer;
    }
    const { payload } = await jwtVerify(token, keys, {
      issuer, audience, algorithms: ['RS256'],
      requiredClaims: ['exp', 'iat', 'sub', 'email'], maxTokenAge: '8h', clockTolerance: 5,
    });
    if (payload.type !== 'app' || typeof payload.email !== 'string' || !payload.sub || payload.common_name) {
      return { canEdit: false, email: null, reason: 'sign_in' };
    }
    const email = payload.email.trim().toLowerCase();
    const canEdit = editors.includes(email);
    return { canEdit, email, reason: canEdit ? 'approved' : 'not_approved' };
  } catch {
    // Invalid, expired or unverifiable tokens never grant edit access.
    return { canEdit: false, email: null, reason: 'sign_in' };
  }
}
