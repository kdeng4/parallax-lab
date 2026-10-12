'use client';
import { useState } from 'react';
import { createAuthClient } from '@neondatabase/auth/next';
const auth = createAuthClient();

export function SignIn({ configured }: { configured: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function signIn() {
    setBusy(true); setError('');
    try {
      const result = await auth.signIn.social({ provider: 'github', callbackURL: '/workspace', errorCallbackURL: '/auth/sign-in' });
      if (result.error) throw new Error('Sign-in failed');
    } catch { setError('GitHub sign-in could not complete. Please try again.'); setBusy(false); }
  }
  return <div>{configured ? <button className="button primary" disabled={busy} onClick={() => void signIn()}>{busy ? 'Connecting…' : 'Continue with GitHub'}</button>
    : <p role="status">Owner sign-in is awaiting GitHub setup. The public dashboard remains available.</p>}
    {error && <p role="alert">{error}</p>}</div>;
}

export function SignOut() {
  const [error, setError] = useState(false);
  return <><button className="text-button" onClick={async () => {
    try { const result = await auth.signOut(); if (result.error) throw new Error(); window.location.assign('/'); }
    catch { setError(true); }
  }}>Sign out</button>{error && <span role="alert">Could not sign out. Try again.</span>}</>;
}
