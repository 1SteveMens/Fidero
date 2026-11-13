'use client';
/* Seller and developer home: what needs you, then reservations on your plots (US-LST-005, US-LST-007). */
import Link from 'next/link';
import { Money, NeedsYou, Skeleton, Status, When, useGet } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { EmptyText, PageHead, Section, items, words, type Page } from '@/components/roles/kit';
import type { Listing } from '@/components/roles/listings';

type Org = { id: string; name: string; kind: string; status: string; my_org_role: string };
type Enquiry = { id: string; status: string };
type Invoice = { id: string; status: string; amount: MoneyT };
type Reservation = {
  id: string; reference: string; status: string; listing: { id: string; reference: string; title: string; status: string }; expires_at: string;
  fresh_search_status: string; fresh_search_date: string | null; escrow: { reference: string; status: string } | null; created_at: string;
};

export default function SellerHome() {
  const orgs = useGet<Page<Org>>('/v1/organisations');
  const listings = useGet<Page<Listing>>('/v1/listings', { mine: 1 });
  const enq = useGet<Page<Enquiry>>('/v1/enquiries', { status: 'open' });
  const inv = useGet<Page<Invoice>>('/v1/seller-invoices');
  const res = useGet<Page<Reservation>>('/v1/reservations');
  const org = items(orgs.data)[0];
  const drafts = items(listings.data).filter((l) => l.status === 'draft');
  const expired = items(listings.data).filter((l) => l.status === 'expired');
  const openEnq = items(enq.data).filter((e) => e.status === 'open');
  const unpaid = items(inv.data).filter((i) => i.status === 'issued' || i.status === 'overdue');
  const live = items(listings.data).filter((l) => l.status === 'live').length;
  return (
    <div className="stack">
      <PageHead label="Selling" title={org?.name ?? 'Selling'}>{org ? `${words(org.kind)} account · you are ${org.my_org_role}` : 'Your listings on Tenmina.'}</PageHead>
      {orgs.isLoading || listings.isLoading ? <Skeleton lines={3} /> : null}
      {openEnq.length ? <NeedsYou title={`${openEnq.length} ${openEnq.length === 1 ? 'enquiry' : 'enquiries'} to answer`} detail="Buyers are waiting for a reply." href="/seller/enquiries" /> : null}
      {unpaid.length ? <NeedsYou title={`${unpaid.length} ${unpaid.length === 1 ? 'invoice' : 'invoices'} to pay`} detail="Listing and success fees." href="/seller/invoices" /> : null}
      {drafts.map((d) => <NeedsYou key={d.id} title={`Send ${d.title} for checking`} detail="Draft listing" href={`/seller/listings/${d.id}`} />)}
      {expired.map((d) => <NeedsYou key={d.id} title={`Re-check ${d.title}`} detail="The badge expired" href={`/seller/listings/${d.id}`} />)}
      <div className="grid3">
        <Link href="/seller/listings" className="card card-link"><div className="label">Live listings</div><div style={{ fontSize: 28, fontWeight: 800 }}>{live}</div></Link>
        <Link href="/seller/listings" className="card card-link"><div className="label">All listings</div><div style={{ fontSize: 28, fontWeight: 800 }}>{items(listings.data).length}</div></Link>
      </div>
      <Section title="Reservations">
        {!res.isLoading && !items(res.data).length ? <EmptyText>No reservations yet.</EmptyText> : null}
        {items(res.data).map((r) => (
          <div key={r.id} className="card stack" style={{ gap: 4 }}>
            <div className="spread"><div><div className="label">{r.reference}</div><strong>{r.listing.title}</strong></div><Status value={r.status} /></div>
            <span style={{ fontSize: 14 }}>Fresh search for the buyer: {words(r.fresh_search_status)}{r.fresh_search_date ? <>, <When value={r.fresh_search_date} /></> : null}.</span>
            {r.escrow ? <span style={{ fontSize: 14 }}>Escrow <span className="mono">{r.escrow.reference}</span>: {words(r.escrow.status)}. The bank pays you when the conditions close.</span> : <span className="muted" style={{ fontSize: 14 }}>Reserved until <When value={r.expires_at} />.</span>}
          </div>
        ))}
      </Section>
      {unpaid.length ? null : items(inv.data).length ? <p className="muted">All invoices paid. Last: <Money value={items(inv.data)[0].amount} />.</p> : null}
    </div>
  );
}
