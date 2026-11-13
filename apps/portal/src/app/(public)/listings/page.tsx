/* Listings search (SCR-PTL-26, US-LST-004, US-LST-010): server-rendered so it loads fast on 3G and search
   engines can read it. Only live and reserved listings with a valid badge appear. */
import type { Metadata } from 'next';
import Link from 'next/link';
import { apiGet, day, money } from '@/components/roles/server-api';
import type { Listing } from '@/components/roles/listings';

export const dynamic = 'force-dynamic';
export const metadata: Metadata = {
  title: 'Checked plots and houses for sale | Tenmina',
  description: 'Plots and houses checked by Tenmina’s lawyers and surveyors. Buy through escrow at a licensed bank.',
};

type SP = Promise<Record<string, string | undefined>>;

export default async function ListingSearch({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const { data, status } = await apiGet<{ items: Listing[] }>('/v1/listings', {
    q: sp.q, kind: sp.kind, locality: sp.locality, max_price: sp.max_price, sort: sp.sort, country: sp.country,
  });
  const rows = data?.items ?? [];
  return (
    <div className="stack">
      <div>
        <p className="label" style={{ margin: 0 }}>Tenmina Verified</p>
        <h1>Checked plots and houses</h1>
        <p className="muted">Each listing has a released Tenmina report behind its badge. When you reserve one, Tenmina runs a fresh search for you and you pay through escrow at a licensed bank.</p>
      </div>
      <form className="card stack" method="get" action="/listings">
        <label className="field"><span>Search</span><input className="input" name="q" defaultValue={sp.q ?? ''} placeholder="Estate, town or plot" /></label>
        <div className="grid2" style={{ gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <label className="field"><span>Type</span>
            <select className="select" name="kind" defaultValue={sp.kind ?? ''}>
              <option value="">Any</option><option value="plot">Plot</option><option value="building">Building</option><option value="estate_plot">Estate plot</option><option value="offplan_unit">Off-plan unit</option>
            </select>
          </label>
          <label className="field"><span>Highest price</span><input className="input" name="max_price" inputMode="decimal" defaultValue={sp.max_price ?? ''} /></label>
        </div>
        <label className="field"><span>Sort</span>
          <select className="select" name="sort" defaultValue={sp.sort ?? ''}>
            <option value="">Newest</option><option value="price">Price, low to high</option><option value="-price">Price, high to low</option>
          </select>
        </label>
        <button className="btn btn-primary" type="submit">Search</button>
      </form>
      {status >= 400 ? <div className="error-box" role="alert"><strong>We could not load listings.</strong><div>Try again in a minute.</div></div> : null}
      {status < 400 && !rows.length ? <div className="card muted" style={{ textAlign: 'center' }}>No checked listings match. Try a wider search.</div> : null}
      <div className="grid3">
        {rows.map((x) => {
          const photo = x.media.find((m) => m.kind === 'photo' && m.public);
          return (
            <Link key={x.id} href={`/listings/${x.id}`} className="card card-link listing-card">
              {photo ? <img src={photo.url} alt={photo.caption || x.title} loading="lazy" /> : null}
              <div className="label">{[x.locality, x.district].filter(Boolean).join(', ')}</div>
              <div style={{ fontWeight: 800, fontSize: 17 }}>{x.title}</div>
              <div style={{ fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>{money(x.price)}</div>
              <div className="row" style={{ marginTop: 6, gap: 8 }}>
                {x.badge ? <span className="chip chip-lime">✓ {x.badge.label}</span> : null}
                {x.status === 'reserved' ? <span className="chip">Reserved</span> : null}
                <span className="muted" style={{ fontSize: 13 }}>Checked {day(x.checks_date)}</span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
