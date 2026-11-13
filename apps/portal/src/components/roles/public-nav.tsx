'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Mark } from '@tenmina/web-ui';

const LINKS = [
  { href: '/listings', label: 'Checked plots' },
  { href: '/check', label: 'Check a report' },
  { href: '/fx', label: 'Exchange rates' },
];

export function PublicNav() {
  const path = usePathname();
  if (path.startsWith('/confirm/')) {
    return <header className="pub-top"><div className="pub-top-inner"><span className="row" style={{ gap: 8, fontWeight: 800 }}><Mark /> Tenmina</span></div></header>;
  }
  return (
    <header className="pub-top">
      <div className="pub-top-inner">
        <Link href="/listings" className="row" style={{ gap: 8, fontWeight: 800 }} aria-label="Tenmina"><Mark /> <span className="rl-brand">Tenmina</span></Link>
        <nav className="pub-links" aria-label="Public pages">
          {LINKS.map((l) => <Link key={l.href} href={l.href} aria-current={path === l.href || path.startsWith(l.href + '/') ? 'page' : undefined}>{l.label}</Link>)}
        </nav>
      </div>
    </header>
  );
}
