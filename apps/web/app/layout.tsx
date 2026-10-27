import './public.css';
import type { Metadata } from 'next';
import Script from 'next/script';
import './globals.css';

export const metadata: Metadata = {
  title: 'Parallax Lab — Trading research, measured.',
  description: 'A paper trading research workbench for reproducible model and strategy comparisons.',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-CA">
      <body>
        {children}
        {process.env.VERCEL_ENV === 'production' && (
          <Script
            src="https://patrick-umami.vercel.app/script.js"
            strategy="afterInteractive"
            data-website-id="879d57a1-9b97-408c-b96f-b14af3b3952b"
            data-domains="parallax.pdeng.pp.ua,parallax-lab-ruddy.vercel.app"
            data-exclude-search="true"
            data-exclude-hash="true"
          />
        )}
      </body>
    </html>
  );
}
