'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Mark, Skeleton, useSession } from '@tenmina/web-ui';
import { NAV, STAFF_ROLES } from '@/lib/nav';
import { CountryChoice, CountryProvider } from '@/components/core/country';

const listOf = (xs: string[]) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}` : xs.join(''));
const ROLE_NAMES: Record<string, string> = { AD: 'administrators', RV: 'reviewers', DPO: 'the data protection officer', PY: 'staff with payment rights', CM: 'case managers' };

export default function WorkLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, signOut, hasRole } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !me) router.replace('/login');
  }, [loading, me, router]);
  useEffect(() => setOpen(false), [path]);

  if (loading || !me) return <main className="bo-main"><Skeleton lines={6} /></main>;
  if (!hasRole(...STAFF_ROLES)) {
    return (
      <main className="bo-main stack">
        <h1>Staff only</h1>
        <p>This is Tenmina&apos;s back office. Clients and field professionals use the portal or the apps.</p>
        <button className="btn btn-dark" onClick={() => signOut()}>Sign out</button>
      </main>
    );
  }
  const active = (href: string) => (href === '/' ? path === '/' : path === href || path.startsWith(href + '/'));
  // A section this person's roles do not open says so, instead of loading lists the API refuses.
  const closed = NAV.flatMap((g) => g.items).find((it) => it.href !== '/' && active(it.href) && it.roles && !hasRole(...it.roles));
  return (
    <CountryProvider>
      <div className="bo">
        <div className="bo-top">
          <button className="btn btn-sm btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="bo-side">Menu</button>
          <span className="row"><Mark size={22} /> Back office</span>
        </div>
        <nav id="bo-side" className={`bo-side ${open ? 'open' : ''}`} aria-label="Sections">
          <div className="bo-brand"><Mark /> Back office</div>
          <div className="bo-nav">
            {NAV.map((g, i) => (
              <div key={i}>
                {g.label ? <div className="bo-group">{g.label}</div> : null}
                {g.items.filter((it) => !it.roles || hasRole(...it.roles)).map((it) => (
                  <Link key={it.href} href={it.href} aria-current={active(it.href) ? 'page' : undefined}>{it.label}</Link>
                ))}
              </div>
            ))}
          </div>
          <div className="bo-me">
            <div style={{ fontWeight: 700 }}>{me.full_name}</div>
            <div className="mono" style={{ fontSize: 12, color: '#a9a69e' }}>{me.roles.join(' · ')}</div>
            <div style={{ marginTop: 8 }}><CountryChoice /></div>
            <button className="btn btn-sm btn-ghost" style={{ marginTop: 8 }} onClick={async () => { await signOut(); router.replace('/login'); }}>Sign out</button>
          </div>
        </nav>
        <main className="bo-main">{closed ? (
          <div className="stack">
            <h1>{closed.label}</h1>
            <p className="muted" style={{ margin: 0 }}>This section is for {listOf((closed.roles ?? []).map((r) => ROLE_NAMES[r] ?? r))}. Ask an administrator if you need it.</p>
          </div>
        ) : children}</main>
      </div>
    </CountryProvider>
  );
}
