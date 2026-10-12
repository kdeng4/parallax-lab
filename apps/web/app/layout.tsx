import './public.css';
import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Parallax Lab — Trading research, measured.',
  description: 'A paper trading research workbench for reproducible model and strategy comparisons.',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en-CA"><body>{children}</body></html>;
}
