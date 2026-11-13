'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Chip, Dialog, Empty, NeedsYou, ProblemBox, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { Item, Section, words, type Any } from '@/components/kit';
import { HeldAtBank } from '@/components/money-cards';
import { familyOf, toPortal } from '@/lib/links';

type HomeItem = { kind: string; id: string; title: string; status: string; status_text: string; next_date: string | null; needs_action: boolean; link: string; line: string; amount: Any; family_member_id: string | null };

const SECTIONS = [
  { key: 'property', title: 'Property', href: '/property' },
  { key: 'family', title: 'Family', href: '/family' },
  { key: 'projects', title: 'Projects', href: '/projects' },
] as const;

const ADD = [
  { href: '/property/order', label: 'A check on land or a building' },
  { href: '/family/members/new', label: 'A family member' },
  { href: '/family/institutions/new', label: 'A school or hospital' },
  { href: '/family/invoices/new', label: 'A bill to pay' },
  { href: '/projects/properties/new', label: 'A property to manage' },
  { href: '/family/errands/new', label: 'An errand' },
  { href: '/family/care/new', label: 'Care visits' },
  { href: '/family/events/new', label: 'An event' },
  { href: '/projects/new', label: 'A project' },
];

/** W-25 · SCR-PTL-36: everything the client has running at home. */
export default function Home() {
  const { me } = useSession();
  const home = useGet<{ items: HomeItem[]; family_members: Any[]; needs_action_count: number }>('/v1/home');
  const countries = useGet<Any>('/v1/countries');
  const [adding, setAdding] = useState(false);
  const [allNeeds, setAllNeeds] = useState(false);
  const items = home.data?.items ?? [];
  const needs = items.filter((i) => i.needs_action);
  const rest = items.filter((i) => !i.needs_action && i.kind !== 'rating_opportunity');
  const country = (Array.isArray(countries.data) ? countries.data : countries.data?.items ?? []).find((c: Any) => c.code === me?.home_country);
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="stack" style={{ gap: 6 }}>
        <div className="spread">
          <p className="label" style={{ margin: 0 }}>At home</p>
          {country ? <Chip>{country.name} · {country.currency ?? country.default_currency ?? ''}</Chip> : null}
        </div>
        <h1 style={{ margin: 0 }}>Hello, {me?.full_name.split(' ')[0]}.</h1>
        {home.data ? <p className="muted" style={{ margin: 0 }}>{needs.length ? `${needs.length} ${needs.length === 1 ? 'thing needs' : 'things need'} you.` : 'Nothing needs you right now.'} {rest.length} running.</p> : null}
      </div>
      {home.isLoading ? <Skeleton lines={5} /> : null}
      <ProblemBox error={home.error} />
      {needs.length ? (
        <section className="stack" aria-label="Needs you" style={{ gap: 10 }}>
          {(allNeeds ? needs : needs.slice(0, 6)).map((n) => <NeedsYou key={`${n.kind}-${n.id}`} title={n.title} detail={n.status_text} href={toPortal(n.link) ?? '/inbox'} />)}
          {needs.length > 6 && !allNeeds ? <button className="btn btn-ghost" onClick={() => setAllNeeds(true)}>Show {needs.length - 6} more that need you</button> : null}
        </section>
      ) : null}
      {me ? <HeldAtBank holder={me.full_name} /> : null}
      <div className="grid2">
        {SECTIONS.map((s) => {
          const mine = rest.filter((i) => familyOf(i.line, i.kind) === s.key);
          if (!mine.length) return null;
          return (
            <Section key={s.key} title={s.title} count={mine.length} action={<Link href={s.href} className="btn btn-ghost btn-sm">See all</Link>}>
              {mine.slice(0, 5).map((i) => (
                <Item key={`${i.kind}-${i.id}`} href={toPortal(i.link)} meta={words(i.kind)} title={i.title} sentence={i.status_text || words(i.status)} amount={i.amount} />
              ))}
            </Section>
          );
        })}
      </div>
      {home.data?.family_members?.length ? (
        <Section title="Your family" action={<Link className="btn btn-ghost btn-sm" href="/family/members/new">Add</Link>}>
          <div className="grid3">
            {home.data.family_members.map((m) => (
              <Item key={m.id} href={`/family/members/${m.id}`} title={m.full_name} sentence={`${words(m.relationship)} · ${m.address || 'No address yet'}`} />
            ))}
          </div>
        </Section>
      ) : null}
      {home.data && !items.length ? <Empty>Nothing running yet. Start with a check on a plot, or add a family member to pay a school or hospital directly.</Empty> : null}
      <button className="btn btn-primary btn-block" onClick={() => setAdding(true)}>+ Add something at home</button>
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add something at home">
        <div className="pt-chooser">
          {ADD.map((a) => <Link key={a.href} href={a.href} className="btn btn-ghost" onClick={() => setAdding(false)}>{a.label}</Link>)}
        </div>
      </Dialog>
    </div>
  );
}
