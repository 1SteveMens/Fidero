'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Empty, Money, NeedsYou, Skeleton, Tabs, Verdict, useGet } from '@tenmina/web-ui';
import { Item, PageHead, Section, list, words, type Any } from '@/components/kit';
import { ESCROW_SENTENCE } from '@/components/escrow-bits';
import { familyOf, toPortal } from '@/lib/links';

const PROPERTY_CASES = ['land', 'building', 'fresh_search', 'offplan_check', 'house'];

/** The Property tab: checks, escrows, listings and disputes (03, 2.1 PROPERTY). */
export default function Property() {
  const [tab, setTab] = useState('checks');
  const home = useGet<Any>('/v1/home');
  const needs = (home.data?.items ?? []).filter((i: Any) => i.needs_action && familyOf(i.line, i.kind) === 'property');
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead label="Property" title="Land and buildings" />
      {needs.map((n: Any) => <NeedsYou key={`${n.kind}-${n.id}`} title={n.title} detail={n.status_text} href={toPortal(n.link)} />)}
      <div className="pt-chooser">
        <Link href="/property/order" className="btn btn-primary">Check land or a building</Link>
        <Link href="/property/listings" className="btn btn-ghost">Find a checked plot</Link>
      </div>
      <Tabs current={tab} onChange={setTab} items={[{ key: 'checks', label: 'Checks' }, { key: 'escrows', label: 'Escrows' }, { key: 'listings', label: 'Listings' }, { key: 'disputes', label: 'Disputes' }, { key: 'more', label: 'More' }]} />
      {tab === 'checks' ? <Checks /> : tab === 'escrows' ? <Escrows /> : tab === 'listings' ? <Listings /> : tab === 'disputes' ? <Disputes /> : <More />}
    </div>
  );
}

function Checks() {
  const orders = useGet<Any>('/v1/orders', { status: 'draft' });
  const toPay = useGet<Any>('/v1/orders', { status: 'awaiting_payment' });
  const cases = useGet<Any>('/v1/cases');
  const reports = useGet<Any>('/v1/reports');
  const drafts = [...list(orders.data), ...list(toPay.data)].filter((o: Any) => ['verification', 'fresh_search'].includes(o.kind));
  const cs = list(cases.data).filter((c: Any) => PROPERTY_CASES.includes(c.product_line));
  const rep = new Map(list(reports.data).filter((r: Any) => r.status === 'released').map((r: Any) => [r.case, r]));
  if (cases.isLoading) return <Skeleton lines={4} />;
  return (
    <div className="stack">
      {drafts.length ? (
        <Section title="Orders to finish">
          {drafts.map((o: Any) => <Item key={o.id} href={`/property/orders/${o.id}`} meta={o.reference} title={`${o.product_name}${o.asset?.locality ? `, ${o.asset.locality}` : ''}`} sentence={o.status === 'draft' ? 'Not sent yet. Finish the order.' : "Pay Tenmina's fee to start."} amount={o.price} />)}
        </Section>
      ) : null}
      <Section title="Checks" count={cs.length}>
        {cs.length ? cs.map((c: Any) => {
          const r = rep.get(c.id) as Any;
          return <Item key={c.id} href={`/property/cases/${c.id}`} meta={`${words(c.product_line)} · ${c.reference}`} title={c.title} sentence={c.latest_status?.text || words(c.status)} chip={r ? <Verdict value={r.overall_verdict} /> : undefined} />;
        }) : <Empty>No checks yet. Start with a check on a plot or a building.</Empty>}
      </Section>
    </div>
  );
}

function Escrows() {
  const q = useGet<Any>('/v1/escrows');
  const rows = list(q.data).filter((e: Any) => !['held_funds', 'event', 'repair'].includes(e.kind));
  if (q.isLoading) return <Skeleton lines={4} />;
  return (
    <Section title="Escrows" count={rows.length}>
      <p className="muted" style={{ margin: 0 }}>A licensed bank holds the money as escrow agent. Tenmina never holds it.</p>
      {rows.length ? rows.map((e: Any) => <Item key={e.id} href={`/property/escrows/${e.id}`} meta={`${words(e.kind)} · ${e.reference}`} title={e.title} sentence={ESCROW_SENTENCE[e.status] ?? words(e.status)} amount={e.agreed_price} />) : <Empty>No escrows yet. You can buy through escrow from a green or amber report.</Empty>}
    </Section>
  );
}

function Listings() {
  const res = useGet<Any>('/v1/reservations');
  const enq = useGet<Any>('/v1/enquiries');
  return (
    <div className="stack">
      <Link href="/property/listings" className="btn btn-dark">Search checked plots</Link>
      <Section title="Reservations">
        {list(res.data).length ? list(res.data).map((r: Any) => <Item key={r.id} href={`/property/reservations/${r.id}`} meta={r.reference} title={r.listing?.title} sentence={words(r.status)} />) : <Empty>No reservations.</Empty>}
      </Section>
      <Section title="Questions you asked">
        {list(enq.data).length ? list(enq.data).map((e: Any) => <Item key={e.id} href={`/property/enquiries/${e.id}`} meta={e.reference} title={e.message} sentence={e.status === 'answered' ? 'Tenmina answered.' : words(e.status)} />) : <Empty>No questions yet.</Empty>}
        <Link href="/property/enquiries/new" className="btn btn-ghost">Ask Tenmina to find a plot</Link>
      </Section>
    </div>
  );
}

function Disputes() {
  const q = useGet<Any>('/v1/disputes');
  if (q.isLoading) return <Skeleton lines={3} />;
  return (
    <Section title="Disputes" count={list(q.data).length} action={<Link href="/property/disputes/new" className="btn btn-ghost btn-sm">Open a dispute</Link>}>
      {list(q.data).length ? list(q.data).map((d: Any) => <Item key={d.id} href={`/property/disputes/${d.id}`} meta={`${d.reference} · ${words(d.status)}`} title={d.subject_label} sentence={d.reason} />) : <Empty>No disputes.</Empty>}
    </Section>
  );
}

function More() {
  const assets = useGet<Any>('/v1/assets');
  const po = useGet<Any>('/v1/partner-orders');
  const pays = useGet<Any>('/v1/payments');
  return (
    <div className="stack">
      <Section title="Your properties">
        {list(assets.data).map((x: Any) => <Item key={x.id} href={`/property/assets/${x.id}`} meta={x.reference} title={x.name || x.locality} sentence={[words(x.type), x.locality, x.verified_at ? 'Checked' : ''].filter(Boolean).join(' · ')} />)}
        {!list(assets.data).length ? <Empty>No properties yet.</Empty> : null}
      </Section>
      <Section title="Partner requests">
        {list(po.data).length ? list(po.data).map((p: Any) => <Item key={p.id} href={`/property/partner-orders/${p.id}`} meta={p.reference} title={`${p.partner}: ${p.locality}`} sentence={words(p.status)} />) : <p className="muted">No partner has asked for a check.</p>}
        <Link href="/property/sharing" className="btn btn-ghost">Sharing with partners and consent</Link>
      </Section>
      <Section title="Fee payments and receipts">
        {list(pays.data).slice(0, 8).map((p: Any) => <Link key={p.id} href={`/property/payments/${p.id}`} className="card card-link spread"><span><span className="mono">{p.order_reference || p.invoice_number}</span> · {words(p.status)}</span><Money value={p.amount} /></Link>)}
      </Section>
    </div>
  );
}
