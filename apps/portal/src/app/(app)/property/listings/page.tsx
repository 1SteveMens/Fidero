'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Button, Chip, Empty, Field, Input, Money, ProblemBox, Select, Skeleton, Tabs, When, useGet } from '@tenmina/web-ui';
import { PageHead, list, useCountry, type Any } from '@/components/kit';

/** W-21 · SCR-PTL-26: search checked plots, as a list or on a map. */
export default function Listings() {
  const country = useCountry();
  const [f, setF] = useState({ locality: '', kind: '', max_price: '', q: '' });
  const [applied, setApplied] = useState<Record<string, string>>({});
  const [view, setView] = useState('list');
  const query = { country: country.code, ...Object.fromEntries(Object.entries(applied).filter(([, v]) => v)) };
  const q = useGet<Any>('/v1/listings', query);
  const map = useGet<Any>(view === 'map' ? '/v1/listings/map' : null, query);
  const rows = list(q.data);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label="Checked plots" title="Find a checked plot" sub="Every plot here has a released Tenmina report. If you reserve one, we run a fresh search for you first." />
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); setApplied(f); }}>
        <Field label="Area"><Input value={f.locality} onChange={(e) => setF({ ...f, locality: e.target.value })} placeholder="For example: Afienya" /></Field>
        <div className="row">
          <div style={{ flex: 1, minWidth: 140 }}><Field label="Type"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="">Any</option><option value="plot">Plot</option><option value="house">House</option><option value="offplan_unit">Off-plan unit</option></Select></Field></div>
          <div style={{ flex: 1, minWidth: 140 }}><Field label={`Up to (${country.currency})`}><Input inputMode="numeric" value={f.max_price} onChange={(e) => setF({ ...f, max_price: e.target.value.replace(/\D/g, '') })} /></Field></div>
        </div>
        <Button variant="dark" type="submit">Search</Button>
      </form>
      <Tabs current={view} onChange={setView} items={[{ key: 'list', label: `List (${rows.length})` }, { key: 'map', label: 'Map' }]} />
      <ProblemBox error={q.error} />
      {view === 'map' ? <ListingMap fc={map.data} rows={rows} /> : q.isLoading ? <Skeleton lines={4} /> : rows.length ? (
        <div className="grid3">
          {rows.map((x: Any) => (
            <Link key={x.id} href={`/property/listings/${x.id}`} className="card card-link stack" style={{ gap: 6, padding: 0, overflow: 'hidden' }}>
              {x.media?.[0]?.url ? <img src={x.media[0].url} alt={x.media[0].caption || x.title} style={{ width: '100%', aspectRatio: '16 / 10', objectFit: 'cover', background: 'var(--color-surface-2)' }} /> : null}
              <div className="stack" style={{ gap: 4, padding: '4px 16px 16px' }}>
                {x.badge ? <Chip tone="lime">✓ {x.badge.label}</Chip> : null}
                <strong>{x.title}</strong>
                <span className="muted" style={{ fontSize: 14 }}>{x.locality}{x.size_sqm ? ` · ${Number(x.size_sqm).toLocaleString('en-GB')} m²` : ''}</span>
                <Money value={x.price} />
                {x.badge ? <span className="mono muted" style={{ fontSize: 12 }}>Checked <When value={x.badge.checks_date} /> · badge until <When value={x.badge.expires_at} /></span> : null}
                {x.reserved ? <Chip>Reserved</Chip> : null}
              </div>
            </Link>
          ))}
        </div>
      ) : <Empty>No checked plots match. <Link href="/property/enquiries/new">Ask us to find one</Link>.</Empty>}
    </div>
  );
}

/** A plain map of result points (no third-party tiles). Plots without a confirmed point stay in the list. */
function ListingMap({ fc, rows }: { fc?: Any; rows: Any[] }) {
  const pts: Any[] = fc?.features ?? [];
  if (!pts.length) return <Empty>None of these plots has a confirmed map point yet. They are all in the list.</Empty>;
  const xs = pts.map((p) => p.geometry.coordinates[0]); const ys = pts.map((p) => p.geometry.coordinates[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => 20 + ((x - minX) / (maxX - minX || 1)) * 260; const sy = (y: number) => 280 - ((y - minY) / (maxY - minY || 1)) * 260;
  return (
    <div className="stack">
      <svg viewBox="0 0 300 300" className="map-box" role="img" aria-label={`${pts.length} plots on the map`}>
        {pts.map((p) => (
          <a key={p.id} href={`/property/listings/${p.id}`}>
            <circle cx={sx(p.geometry.coordinates[0])} cy={sy(p.geometry.coordinates[1])} r="9" fill="#a3ee5b" stroke="#0b0b0b" strokeWidth="2" />
            <title>{p.properties?.title}</title>
          </a>
        ))}
      </svg>
      <p className="muted" style={{ fontSize: 14 }}>{rows.length - pts.length} of the results have no map point and are shown only in the list.</p>
    </div>
  );
}
