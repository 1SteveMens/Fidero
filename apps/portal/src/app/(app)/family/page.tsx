'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Empty, NeedsYou, Skeleton, Tabs, useGet, useSession } from '@tenmina/web-ui';
import { Item, PageHead, Section, list, words, type Any } from '@/components/kit';
import { HeldAtBank } from '@/components/money-cards';
import { familyOf, toPortal } from '@/lib/links';

/** The Family tab (03, 2.1 FAMILY): people, bills paid direct to institutions, care, errands, cover and events. */
export default function Family() {
  const { me } = useSession();
  const [tab, setTab] = useState('people');
  const home = useGet<Any>('/v1/home');
  const needs = (home.data?.items ?? []).filter((i: Any) => i.needs_action && familyOf(i.line, i.kind) === 'family');
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead label="Family" title="Your family at home" sub="Tenmina pays schools, hospitals and vendors directly, against proof. Never cash to a relative." />
      {needs.map((n: Any) => <NeedsYou key={`${n.kind}-${n.id}`} title={n.title} detail={n.status_text} href={toPortal(n.link)} />)}
      {me ? <HeldAtBank holder={me.full_name} kinds={['held_funds']} /> : null}
      <Tabs current={tab} onChange={setTab} items={[{ key: 'people', label: 'People' }, { key: 'bills', label: 'Bills' }, { key: 'care', label: 'Care' }, { key: 'errands', label: 'Errands' }, { key: 'cover', label: 'Cover' }, { key: 'events', label: 'Events' }]} />
      {tab === 'people' ? <People /> : tab === 'bills' ? <Bills /> : tab === 'care' ? <Care /> : tab === 'errands' ? <Errands /> : tab === 'cover' ? <Cover /> : <Events />}
    </div>
  );
}

function People() {
  const q = useGet<Any>('/v1/family-members');
  if (q.isLoading) return <Skeleton lines={3} />;
  return (
    <Section title="Family members" action={<Link href="/family/members/new" className="btn btn-ghost btn-sm">Add</Link>}>
      {list(q.data).filter((m: Any) => m.status !== 'removed').length ? list(q.data).filter((m: Any) => m.status !== 'removed').map((m: Any) => <Item key={m.id} href={`/family/members/${m.id}`} meta={words(m.relationship)} title={m.full_name} sentence={m.address || m.phone} />) : <Empty>Add a family member to pay a school or hospital for them.</Empty>}
    </Section>
  );
}

function Bills() {
  const inv = useGet<Any>('/v1/invoices');
  const sch = useGet<Any>('/v1/fee-schedules');
  const inst = useGet<Any>('/v1/institutions');
  return (
    <div className="stack">
      <div className="pt-chooser">
        <Link href="/family/invoices/new" className="btn btn-primary">Add a bill</Link>
        <Link href="/family/institutions/new" className="btn btn-ghost">Add a school or hospital</Link>
        <Link href="/family/schedules/new" className="btn btn-ghost">Set up regular fees</Link>
      </div>
      <Section title="Bills" count={list(inv.data).length}>
        {inv.isLoading ? <Skeleton /> : list(inv.data).length ? list(inv.data).map((i: Any) => <Item key={i.id} href={`/family/invoices/${i.id}`} meta={`${i.institution?.name}${i.family_member ? ` · ${i.family_member.full_name}` : ''}`} title={i.description || i.institution_reference} sentence={i.status_text} amount={i.amount} needs={['checked'].includes(i.status)} />) : <Empty>No bills yet.</Empty>}
      </Section>
      <Section title="Regular fees">
        {list(sch.data).length ? list(sch.data).map((s: Any) => <Item key={s.id} href={`/family/schedules/${s.id}`} meta={`Every ${s.period}`} title={s.label} sentence={`Next due ${s.next_due_on}. We remind you and ask for your approval each time.`} amount={s.expected} />) : <p className="muted">No regular fees.</p>}
      </Section>
      <Section title="Schools, hospitals and providers">
        {list(inst.data).map((i: Any) => <Item key={i.id} href={`/family/institutions/${i.id}`} meta={words(i.type)} title={i.legal_name} sentence={i.status_text} chip={i.status === 'verified' ? <span className="proof">✓ Verified</span> : undefined} />)}
      </Section>
    </div>
  );
}

function Care() {
  const plans = useGet<Any>('/v1/care-plans');
  const visits = useGet<Any>('/v1/care-visits');
  const concerns = useGet<Any>('/v1/concerns');
  return (
    <div className="stack">
      <Link href="/family/care/new" className="btn btn-primary">Arrange care visits</Link>
      <Section title="Care plans">
        {list(plans.data).length ? list(plans.data).map((p: Any) => <Item key={p.id} href={`/family/care/${p.id}`} meta={`${p.reference} · ${words(p.status)}`} title={`Care visits for ${p.family_member?.full_name ?? 'your relative'}`} sentence={p.needs_client ? `Needs you: ${words(p.needs_client)}` : p.next_visit_at ? `Next visit ${new Date(p.next_visit_at).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}` : words(p.status)} needs={!!p.needs_client} />): <Empty>No care plans yet.</Empty>}
      </Section>
      <Section title="Recent visits">
        {list(visits.data).slice(0, 8).map((v: Any) => <Item key={v.id} href={`/family/visits/${v.id}`} meta={new Date(v.window_start).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} title={`${v.carer?.name ?? 'Carer'} visits ${v.family_member?.full_name ?? ''}`} sentence={words(v.status)} />)}
      </Section>
      {list(concerns.data).length ? <Section title="Concerns">{list(concerns.data).map((c: Any) => <Item key={c.id} href={`/family/concerns/${c.id}`} meta={`${c.reference} · ${words(c.status)}`} title={`${words(c.kind)} concern (${c.severity}), ${c.family_member?.full_name ?? ''}`} />)}</Section> : null}
    </div>
  );
}

function Errands() {
  const q = useGet<Any>('/v1/errands');
  return (
    <div className="stack">
      <Link href="/family/errands/new" className="btn btn-primary">Get paperwork done</Link>
      <Section title="Errands">
        {list(q.data).length ? list(q.data).map((e: Any) => <Item key={e.id} href={`/family/errands/${e.id}`} meta={e.reference} title={e.name} sentence={e.status_text || words(e.status)} />) : <Empty>No errands yet.</Empty>}
      </Section>
    </div>
  );
}

function Cover() {
  const prods = useGet<Any>('/v1/insurance/products');
  const apps = useGet<Any>('/v1/insurance/applications');
  const pols = useGet<Any>('/v1/insurance/policies');
  const prem = useGet<Any>('/v1/insurance/premiums');
  const claims = useGet<Any>('/v1/insurance/claims');
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>Cover is a licensed insurer&apos;s product. Tenmina does not hold the risk.</p>
      <Section title="Policies">{list(pols.data).length ? list(pols.data).map((p: Any) => <Item key={p.id} href={`/family/insurance/policies/${p.id}`} meta={`${p.insurer_name} · ${p.policy_number}`} title={p.product_name} sentence={`${words(p.status)}. Renews ${p.renews_on}.`} />) : <p className="muted">No policies.</p>}</Section>
      {list(prem.data).length ? <Section title="Premiums">{list(prem.data).map((p: Any) => <Item key={p.id} href={`/family/insurance/premiums/${p.id}`} meta={`Due ${p.due_on}`} title={`${p.insurer_name} · ${p.policy_number}`} sentence={words(p.status)} amount={p.amount} needs={p.status === 'due'} />)}</Section> : null}
      {list(claims.data).length ? <Section title="Claims">{list(claims.data).map((c: Any) => <Item key={c.id} href={`/family/insurance/claims/${c.id}`} meta={c.insurer_reference} title={c.description} sentence={c.status_text} />)}</Section> : null}
      {list(apps.data).length ? <Section title="Applications">{list(apps.data).map((x: Any) => <Item key={x.id} href={`/family/insurance/applications/${x.id}`} meta={x.insurer_name} title={x.product_name} sentence={x.status_text} />)}</Section> : null}
      <Section title="Cover you can apply for">{list(prods.data).map((p: Any) => <Item key={p.id} href={`/family/insurance/products/${p.id}`} meta={p.insurer_name} title={p.name} sentence={p.summary || words(p.kind)} />)}</Section>
    </div>
  );
}

function Events() {
  const q = useGet<Any>('/v1/events');
  return (
    <div className="stack">
      <Link href="/family/events/new" className="btn btn-primary">Plan an event</Link>
      <Section title="Events">
        {list(q.data).length ? list(q.data).map((e: Any) => <Item key={e.id} href={`/family/events/${e.id}`} meta={`${words(e.kind)} · ${e.event_date}`} title={e.name} sentence={words(e.status)} amount={e.budget} />) : <Empty>No events yet.</Empty>}
      </Section>
    </div>
  );
}
