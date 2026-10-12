export type EditorAccess = {
  canView: boolean;
  canEdit: boolean;
  email: string | null;
  reason: 'approved' | 'local' | 'sign_in' | 'not_approved' | 'not_configured';
};

const denied = (reason: EditorAccess['reason']): EditorAccess => ({ canView: false, canEdit: false, email: null, reason });
const emails = (value = '') => value.split(',').map(v => v.trim().toLowerCase()).filter(Boolean);

export function authorizeGoogle(session: { user?: { email?: string; emailVerified?: boolean }; session?: { expiresAt?: Date | string } } | null,
  accounts: { providerId: string }[], editors: string, viewers = ''): EditorAccess {
  if (!session?.user?.email || session.user.emailVerified !== true || !session.session?.expiresAt
    || !Number.isFinite(new Date(session.session.expiresAt).getTime())
    || new Date(session.session.expiresAt).getTime() <= Date.now()
    || !accounts.some(account => account.providerId === 'google')) return denied('sign_in');
  const email = session.user.email.trim().toLowerCase();
  const canEdit = emails(editors).includes(email);
  const canView = canEdit || emails(viewers).includes(email);
  return { canView, canEdit, email, reason: canView ? 'approved' : 'not_approved' };
}

export async function editorAccess(request: Request): Promise<EditorAccess> {
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(new URL(request.url).hostname);
  if (process.env.VERCEL !== '1' && local && process.env.PARALLAX_LOCAL_WRITE_ACCESS === '1')
    return { canView: true, canEdit: true, email: null, reason: 'local' };
  if (!process.env.NEON_AUTH_BASE_URL || (process.env.NEON_AUTH_COOKIE_SECRET?.length ?? 0) < 32
    || process.env.NEON_AUTH_GOOGLE_READY !== '1' || !process.env.PARALLAX_EDITOR_EMAILS) return denied('not_configured');
  try {
    const { authServer } = await import('./auth-server.ts');
    const auth = authServer();
    const { data: session } = await auth.getSession();
    if (!session?.user) return denied('sign_in');
    const { data: accounts } = await auth.listAccounts();
    return authorizeGoogle(session, accounts ?? [], process.env.PARALLAX_EDITOR_EMAILS, process.env.PARALLAX_VIEWER_EMAILS);
  } catch { return denied('sign_in'); }
}
