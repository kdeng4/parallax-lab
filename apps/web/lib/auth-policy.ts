// Preserve the managed SDK's session/callback flow while removing unused
// registration, account-linking and alternative sign-in entry points.
export async function allowedAuthRequest(request: Request, path: string[]): Promise<boolean> {
  const route = path.join('/');
  if (route === 'sign-up' || route.startsWith('sign-up/') || ['link-social', 'unlink-account', 'set-password', 'change-password',
    'change-email', 'update-user', 'delete-user', 'request-password-reset', 'reset-password'].includes(route)) return false;
  if (route !== 'sign-in' && !route.startsWith('sign-in/')) return true;
  if (route !== 'sign-in/social' || request.method !== 'POST') return false;
  try {
    const body = await request.clone().json();
    // Identity scopes come from Neon's GitHub provider; callers cannot expand them.
    return body.provider === 'github' && body.scopes === undefined && body.additionalParams === undefined;
  } catch { return false; }
}
