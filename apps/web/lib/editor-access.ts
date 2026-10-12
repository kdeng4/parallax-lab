export type EditorAccess = {
  canView: boolean;
  canEdit: boolean;
  email: string | null;
  reason: 'approved' | 'local' | 'sign_in' | 'not_approved' | 'not_configured';
};

const denied = (reason: EditorAccess['reason']): EditorAccess => ({ canView: false, canEdit: false, email: null, reason });
export function authorizeGitHub(session: { user?: { email?: string | null }; session?: { expiresAt?: Date | string } } | null,
  accounts: { providerId: string; accountId?: string }[], ownerId: string): EditorAccess {
  if (!/^[1-9]\d*$/.test(ownerId)) return denied('not_configured');
  if (!session?.user || !session.session?.expiresAt
    || !Number.isFinite(new Date(session.session.expiresAt).getTime())
    || new Date(session.session.expiresAt).getTime() <= Date.now()
    || !accounts.some(account => account.providerId === 'github')) return denied('sign_in');
  // Use the provider's immutable subject. Usernames and emails are not authority.
  const approved = accounts.some(account => account.providerId === 'github' && account.accountId === ownerId);
  return { canView: approved, canEdit: approved, email: session.user.email?.trim().toLowerCase() ?? null,
    reason: approved ? 'approved' : 'not_approved' };
}

export async function editorAccess(request: Request): Promise<EditorAccess> {
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(new URL(request.url).hostname);
  if (process.env.VERCEL !== '1' && local && process.env.PARALLAX_LOCAL_WRITE_ACCESS === '1')
    return { canView: true, canEdit: true, email: null, reason: 'local' };
  if (!process.env.NEON_AUTH_BASE_URL || (process.env.NEON_AUTH_COOKIE_SECRET?.length ?? 0) < 32
    || process.env.NEON_AUTH_GITHUB_READY !== '1' || !/^[1-9]\d*$/.test(process.env.PARALLAX_OWNER_GITHUB_ID ?? '')) return denied('not_configured');
  try {
    const { authServer } = await import('./auth-server.ts');
    const auth = authServer();
    const { data: session } = await auth.getSession();
    if (!session?.user) return denied('sign_in');
    const { data: accounts } = await auth.listAccounts();
    return authorizeGitHub(session, accounts ?? [], process.env.PARALLAX_OWNER_GITHUB_ID!);
  } catch { return denied('sign_in'); }
}
