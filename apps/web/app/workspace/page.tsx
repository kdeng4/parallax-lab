import { headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { editorAccess } from '@/lib/editor-access';
import { Workbench } from '@/components/workbench';

export default async function Workspace() {
  const incoming = await headers();
  const host = incoming.get('host') ?? 'parallax.pdeng.pp.ua';
  const access = await editorAccess(new Request(`${process.env.VERCEL === '1' ? 'https' : 'http'}://${host}/workspace`, { headers: incoming }));
  if (!access.canView) redirect('/auth/sign-in');
  return <Workbench />;
}
