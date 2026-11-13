import type { Metadata, Viewport } from 'next';
import '@tenmina/web-ui/src/bloc.css';
import './portal.css';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'Tenmina',
  description: 'Your trusted agent at home: checked, paid against proof and shown to you.',
};
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#0B0B0B' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
