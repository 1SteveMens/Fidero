'use client';
import { SessionProvider } from '@tenmina/web-ui';

export function Providers({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
