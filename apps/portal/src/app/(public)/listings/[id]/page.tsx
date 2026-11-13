/* Listing detail (SCR-PTL-27, US-LST-003, US-LST-010, RUL-12 to RUL-14): badge, check date and expiry,
   the seller's track record, the checked plots disclosure, and reserve or ask a question when signed in.
   Server-rendered; indexed only while live. */
import type { Metadata } from 'next';
import Link from 'next/link';
import { apiGet, day, money } from '@/components/roles/server-api';
import type { Listing } from '@/components/roles/listings';
import { ListingActions } from '@/components/roles/listing-actions';

export const dynamic = 'force-dynamic';
type P = Promise<{ id: string }>;

export async function generateMetadata({ params }: { params: P }): Promise<Metadata> {
  const { id } = await params;
  const { data } = await apiGet<Listing>(`/v1/listings/${id}`);
  if (!data) return { title: 'Listing not found | Tenmina', robots: { index: false, follow: false } };
  return {
    title: `${data.title} | Tenmina Verified`,
    description: `${data.title}, ${data.locality}. ${money(data.price)}. Checked by Tenmina on ${day(data.checks_date)}.`,
    robots: data.status === 'live' ? { index: true, follow: true } : { index: false, follow: true },
    alternates: { canonical: `/listings/${data.id}` },
  };
}

export default async function ListingDetail({ params }: { params: P }) {
  const { id } = await params;
  const { data: x, status } = await apiGet<Listing>(`/v1/listings/${id}`);
  if (!x) {
    return (
      <div className="stack">
        <h1>{status === 404 ? 'This listing is not available' : 'We could not load this listing'}</h1>
        <p className="muted">{status === 404 ? 'It may be sold, withdrawn or its check may have expired.' : 'Try again in a minute.'}</p>
        <Link className="btn btn-primary" href="/listings">See checked listings</Link>
      </div>
    );
  }
  const photos = x.media.filter((m) => m.kind === 'photo' && m.public);
  const ld = { '@context': 'https://schema.org', '@type': 'Product', name: x.title, description: x.description, offers: { '@type': 'Offer', price: x.price.amount, priceCurrency: x.price.currency } };
  return (
    <article className="stack">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />
      <Link href="/listings" className="muted" style={{ textDecoration: 'none', fontWeight: 700 }}>← Checked plots</Link>
      <div>
        <p className="label" style={{ margin: 0 }}>{[x.estate_name, x.locality, x.district, x.region].filter(Boolean).join(' · ')}</p>
        <h1>{x.title}</h1>
        <div className="row"><strong style={{ fontSize: 24, fontVariantNumeric: 'tabular-nums' }}>{money(x.price)}</strong>{x.size_sqm ? <span className="muted">{Number(x.size_sqm).toLocaleString('en-GB')} m²</span> : null}{x.status === 'reserved' ? <span className="chip">Reserved</span> : null}</div>
      </div>
      {photos.length ? <div className="photo-strip">{photos.map((m) => <img key={m.id} src={m.url} alt={m.caption || x.title} />)}</div> : null}
      {x.badge ? (
        <div className="card-ink stack">
          <span className="chip chip-lime" style={{ alignSelf: 'flex-start' }}>✓ {x.badge.label}</span>
          <div className="statline"><span>Checked on</span><span className="v">{day(x.badge.checks_date)}</span></div>
          <div className="statline"><span>Badge valid until</span><span className="v">{day(x.badge.expires_at)}</span></div>
          <div className="statline"><span>Report</span><span className="v mono">{x.badge.report_reference}</span></div>
          <p style={{ margin: 0, fontSize: 14 }}>The check is not a guarantee of title. When you reserve, Tenmina runs a fresh search for you before any money moves.</p>
        </div>
      ) : null}
      {x.description ? <p style={{ whiteSpace: 'pre-wrap' }}>{x.description}</p> : null}
      {x.seller ? (
        <div className="card">
          <div className="label">Seller</div>
          <strong>{x.seller.name}</strong>
          <div className="muted" style={{ fontSize: 14 }}>{x.seller.kind === 'developer' ? 'Developer' : 'Seller'}{x.seller.established ? ' · established seller, checked by Tenmina' : ''}</div>
        </div>
      ) : null}
      <div className="banner-info" style={{ fontSize: 14 }}>{x.disclosure}</div>
      <ListingActions id={x.id} live={x.status === 'live'} hasReport={!!x.badge} />
      <p className="muted" style={{ fontSize: 13 }}>Your money is held by the partner bank, never by Tenmina. Tenmina never asks you to pay a seller directly.</p>
    </article>
  );
}
