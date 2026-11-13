'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { Mark, Skeleton, useSession } from '@tenmina/web-ui';
import { TABS } from '@/lib/nav';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { me, loading } = useSession();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [loading, me, router, path]);
  const active = (href: string) => (href === '/' ? path === '/' : path === href || path.startsWith(href + '/'));
  return (
    <>
      <header className="pt-top">
        <div className="pt-top-inner">
          <Link href="/" aria-label="Tenmina home" className="row" style={{ textDecoration: 'none', color: '#fff', fontWeight: 800 }}><Mark /> <span>Tenmina</span></Link>
          <nav className="pt-tabs" aria-label="Sections">
            {TABS.map((t) => <Link key={t.href} href={t.href} aria-current={active(t.href) ? 'page' : undefined}>{t.label}</Link>)}
          </nav>
          <Link href="/inbox" className="btn btn-sm btn-ghost" style={{ color: '#fff' }} aria-label="Messages">Inbox</Link>
        </div>
      </header>
      <main className="pt-main">{loading || !me ? <Skeleton lines={6} /> : children}</main>
      <nav className="pt-bottom" aria-label="Sections">
        {TABS.map((t) => <Link key={t.href} href={t.href} aria-current={active(t.href) ? 'page' : undefined}>{t.label}</Link>)}
      </nav>
    </>
  );
}
