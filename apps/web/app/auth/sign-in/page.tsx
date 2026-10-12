import { headers } from 'next/headers';
import { SignIn } from '@/components/sign-in';
import { authConfigured } from '@/lib/auth-server';
import { editorAccess } from '@/lib/editor-access';
import { redirect } from 'next/navigation';

export default async function SignInPage() {
  const incoming = await headers();
  const access = await editorAccess(new Request('https://parallax.pdeng.pp.ua/auth/sign-in', { headers: incoming }));
  if (access.canView) redirect('/workspace');
  return <div className="public-shell"><main className="sign-in-panel"><a href="/" className="text-button">← Public dashboard</a>
    <p className="eyebrow">PRIVATE WORKSPACE</p><h1>Owner sign-in.</h1>
    <p>Market data, research settings and new experiments are available only to approved accounts.</p>
    {access.reason === 'not_approved' && <p role="alert">This Google account has not been approved for the workspace.</p>}
    <SignIn configured={authConfigured()} /></main></div>;
}
