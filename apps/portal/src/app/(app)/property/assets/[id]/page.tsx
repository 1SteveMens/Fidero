'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Button, Chip, KV, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { PageHead, Proof, Section, list, useAction, words, type Any } from '@/components/kit';
import { PlotDrawer, type LngLat } from '@/components/plot-drawer';

/** A property the client owns or is buying: details, its boundary, and a fresh search (FR-GEO-001, FR-CASE-014). */
export default function Asset() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const q = useGet<Any>(`/v1/assets/${id}`);
  const b = useGet<Any>(`/v1/assets/${id}/boundary`, undefined, { shouldRetryOnError: false });
  const cases = useGet<Any>('/v1/cases');
  const [draw, setDraw] = useState(false);
  const [points, setPoints] = useState<LngLat[]>([]);
  const [centre, setCentre] = useState<LngLat | null>(null);
  const a = useAction();
  if (q.isLoading) return <Skeleton lines={5} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const x = q.data;
  const myCases = list(cases.data).filter((c: Any) => c.asset === id);
  const parent = myCases.find((c: Any) => c.order);
  const start = centre ?? x.location ?? b.data?.properties?.centroid ?? null;
  async function freshSearch() {
    await a.run('fs', () => a.post<Any>('/v1/orders', { country: x.country, kind: 'fresh_search', draft: true, parent_order_id: parent?.order, asset: { type: x.type === 'building' ? 'building' : 'plot', locality: x.locality, plot_number: x.plot_number, site_plan_ref: x.site_plan_ref, ghana_post_gps: x.ghana_post_gps } }), undefined, (o) => router.push(`/property/orders/${o.id}?step=4`));
  }
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${words(x.type)} · ${x.reference}`} title={x.name || x.locality} />
      {x.disputed_flag ? <Blocked title="Marked as disputed">{x.disputed_reason}</Blocked> : null}
      <KV items={[
        ['Area', [x.locality, x.district, x.region].filter(Boolean).join(', ')],
        ['Address', x.address || '—'], ['Plot number', x.plot_number || '—'], ['Site plan', x.site_plan_ref || '—'], ['Ghana Post GPS', x.ghana_post_gps || '—'],
        ['Checked', x.verified_at ? <Proof key="v">Checked <When value={x.verified_at} /></Proof> : 'Not yet'],
        ['Monitoring', x.monitoring_active ? `On${x.open_alerts ? `, ${x.open_alerts} open alert(s)` : ''}` : 'Off'],
      ]} />
      <Section title="Boundary">
        {b.data ? (
          <div className="card stack" style={{ gap: 4 }}>
            <div>Version {b.data.properties?.version} · {words(b.data.properties?.source)} · <When value={b.data.properties?.created_at} /></div>
            <div className="muted">{Number(b.data.properties?.area_sqm || 0).toLocaleString('en-GB')} m² ({b.data.properties?.area_acres} acres)</div>
          </div>
        ) : <p className="muted" style={{ margin: 0 }}>No boundary saved yet. The surveyor records the measured one. You can draw a sketch to help.</p>}
        {draw ? (
          <div className="card stack">
            {!start ? (
              <Button variant="ghost" onClick={() => navigator.geolocation?.getCurrentPosition((p) => setCentre({ lng: p.coords.longitude, lat: p.coords.latitude }))}>Start from where I am</Button>
            ) : <PlotDrawer centre={start} points={points} onChange={setPoints} />}
            <Button variant="primary" disabled={points.length < 3} busy={a.busy === 'b'} onClick={() => a.run('b', () => a.post(`/v1/assets/${id}/boundary`, { source: 'drawn', points, note: 'Drawn by the owner in the portal' }, 'PUT'), 'Sketch saved', () => { setDraw(false); b.mutate(); })}>Save my sketch</Button>
          </div>
        ) : <Button variant="ghost" onClick={() => setDraw(true)}>Draw the plot</Button>}
      </Section>
      <Section title="Checks on this property">
        {myCases.map((c: Any) => <Link key={c.id} href={`/property/cases/${c.id}`} className="card card-link spread"><span>{c.title}</span><Chip>{words(c.status)}</Chip></Link>)}
        <p className="muted" style={{ margin: 0 }}>A fresh search checks the registry again before money is released or when you reserve a plot.</p>
        <Button variant="dark" busy={a.busy === 'fs'} onClick={freshSearch}>Order a fresh search</Button>
      </Section>
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}
