'use client';
/* Portal pages for everyone who is not the client: professionals, sellers and developers, contractors,
   institution contacts, insurers, partners, family members, tenants and authority representatives
   (03 section 2.1, DA-13). Same black top bar as the client portal; tabs suit the role; each section
   opens only for its roles. */
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Mark, Skeleton, useSession } from '@tenmina/web-ui';
import { ROLE_HOME } from '@/lib/nav';
import { SECTIONS, sectionFor, tabsFor } from '@/components/roles/sections';
import { NotAllowed } from '@/components/roles/kit';
import '@/components/roles/roles.css';

export default function RolesLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, signOut } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [loading, me, router, path]);
  useEffect(() => setMenu(false), [path]);

  const section = sectionFor(path);
  const roles = me?.roles ?? [];
  const allowed = !!section && section.roles.some((r) => roles.includes(r));
  const tabs = section && allowed ? tabsFor(section, roles) : [];
  const homes = SECTIONS.filter((s) => s.roles.some((r) => roles.includes(r)));
  const myHome = roles.map((r) => ROLE_HOME[r]).find(Boolean);
  const active = (href: string) => {
    if (href === section?.prefix) return path === href;
    return path === href || path.startsWith(href + '/');
  };

  return (
    <>
      <header className="pt-top">
        <div className="pt-top-inner">
          <Link href={section?.prefix ?? '/'} aria-label="Tenmina" className="row" style={{ textDecoration: 'none', color: '#fff', fontWeight: 800, gap: 8 }}>
            <Mark /> <span className="rl-brand">Tenmina</span>
          </Link>
          <nav className="pt-tabs" aria-label="Sections">
            {tabs.map((t) => <Link key={t.href} href={t.href} aria-current={active(t.href) ? 'page' : undefined}>{t.label}</Link>)}
          </nav>
          <span className="rl-section">{section?.name}</span>
          <div style={{ position: 'relative' }}>
            <button type="button" className="btn btn-sm btn-ghost rl-menu-btn" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
              {me ? me.full_name.split(' ')[0] : 'Menu'}
            </button>
            {menu ? (
              <div className="rl-menu" role="menu">
                {homes.length > 1 ? homes.map((h) => <Link key={h.prefix} role="menuitem" href={h.prefix}>{h.name}</Link>) : null}
                {roles.includes('CL') ? <Link role="menuitem" href="/">My things at home</Link> : null}
                <button type="button" role="menuitem" onClick={async () => { await signOut(); router.replace('/login'); }}>Sign out</button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <main className="pt-main">
        {loading || !me ? <Skeleton lines={6} /> : allowed ? children : <NotAllowed home={myHome} />}
      </main>
      {tabs.length > 1 ? (
        <nav className="pt-bottom" aria-label="Sections">
          {tabs.map((t) => <Link key={t.href} href={t.href} aria-current={active(t.href) ? 'page' : undefined}>{t.label}</Link>)}
        </nav>
      ) : null}
    </>
  );
}
