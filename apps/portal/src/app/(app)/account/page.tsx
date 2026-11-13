'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button, NeedsYou, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, words, type Any } from '@/components/kit';
import { familyOf, toPortal } from '@/lib/links';

const LINKS = [
  { href: '/account/profile', label: 'Profile', sub: 'Name, phone, email, language' },
  { href: '/account/security', label: 'Sign-in and authenticator app', sub: 'Password and the code for approvals' },
  { href: '/account/identity', label: 'Identity check', sub: 'Needed before your first report or escrow' },
  { href: '/account/bank-accounts', label: 'Bank accounts', sub: 'Your own accounts, for rent and refunds' },
  { href: '/account/representatives', label: 'Representatives', sub: 'Someone you trust who can follow a case' },
  { href: '/account/notifications', label: 'Notifications', sub: 'How we contact you' },
  { href: '/property/sharing', label: 'Sharing and consent', sub: 'Partners and case studies' },
  { href: '/account/privacy', label: 'Privacy and my data', sub: 'The notice, a copy of your data, corrections' },
  { href: '/account/referral', label: 'Referral code', sub: 'A discount for people you refer' },
  { href: '/account/delete', label: 'Delete my account', sub: 'What is deleted and what is kept' },
];

/** SCR-PTL-20, SCR-PTL-34: Account, on black (6.1a). */
export default function Account() {
  const { me: session, signOut } = useSession();
  const me = session as (typeof session & Any) | null;
  const router = useRouter();
  const home = useGet<Any>('/v1/home');
  const needs = (home.data?.items ?? []).filter((i: Any) => i.needs_action && familyOf(i.line, i.kind) === 'account');
  if (!me) return null;
  return (
    <Ink>
      <PageHead label="Account" title={me.full_name} sub={`${me.email} · ${me.phone || 'no phone'}`} />
      <div className="row">
        {me.email_verified ? <Proof>Email confirmed</Proof> : null}
        {me.phone_verified ? <Proof>Phone confirmed</Proof> : null}
        {me.mfa_enabled ? <Proof>Authenticator app on</Proof> : null}
        {me.id_check_status === 'passed' ? <Proof>Identity checked</Proof> : null}
      </div>
      {!me.mfa_enabled ? <NeedsYou title="Set up your authenticator app" detail="You need it to approve any payment." href="/account/security" /> : null}
      {me.privacy_notice_pending ? <NeedsYou title="Read the new privacy notice" detail="It changed since you last accepted it." href="/account/privacy" /> : null}
      {needs.map((n: Any) => <NeedsYou key={`${n.kind}-${n.id}`} title={n.title} detail={n.status_text} href={toPortal(n.link)} />)}
      <nav className="stack" style={{ gap: 8 }} aria-label="Account">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className="card card-link spread" style={{ flexWrap: 'nowrap' }}>
            <span><strong>{l.label}</strong><div className="muted" style={{ fontSize: 14 }}>{l.sub}</div></span><span aria-hidden>→</span>
          </Link>
        ))}
      </nav>
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>Roles: {me.roles.map((r: string) => words(r)).join(', ')} · home country {me.home_country}</p>
      <Button variant="ghost" onClick={async () => { await signOut(); router.replace('/login'); }}>Sign out</Button>
    </Ink>
  );
}
