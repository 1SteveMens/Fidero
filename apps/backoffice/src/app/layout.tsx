import type { Metadata } from 'next';
import '@tenmina/web-ui/src/bloc.css';
import './backoffice.css';
import { Providers } from './providers';

export const metadata: Metadata = { title: 'Tenmina back office', description: 'Staff work, cases, escrow, reports and payment runs' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
