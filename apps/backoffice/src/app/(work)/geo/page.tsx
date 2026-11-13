'use client';
/* Maps and layers (SCR-BO-07): the area map with plots and overlay layers, the asset list, overlap flags
 * (FR-GEO-005), monitoring alerts (FR-GEO-007) and the overlay layers with their versions (FR-GEO-004). */
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, call, Empty, Field, Input, ProblemBox, Select, Skeleton, Tabs, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, Head, useAct, words } from '@/components/core/kit';
import { GeoMap, type FC } from '@/components/core/GeoMap';
import type { Asset, Page } from '@/components/core/types';

type Layer = { id: string; code: string; name: string; kind: string; description: string; buffer_m: string | null; effective_buffer_m: string; status: string; is_sample: boolean; current_version: { id: string; version: number; status: string; source: string; valid_from: string | null; feature_count: number; created_at: string } | null };
type Overlap = { id: string; asset: string; asset_reference: string; other_asset: { id: string; reference: string; locality: string; plot_number: string; owner_name: string } | null; other_kind: string; overlap_area_sqm: string; overlap_share: string; other_overlap_share: string; status: string; resolution: string; resolution_note: string; resolved_by_name: string | null; created_at: string };
type Alert = { id: string; asset: string; asset_reference: string; previous_date: string | null; new_date: string | null; change_score: string; threshold: string; change_kind: string; status: string; assigned_to_name: string; resolution: string; resolution_note: string; created_at: string; previous_image: { content_url: string } | null; new_image: { content_url: string } | null };

const AREAS: Record<string, string> = { 'Accra sample area': '-0.25,5.65,-0.05,5.85', 'Greater Accra': '-0.6,5.45,0.7,6.1', Ghana: '-3.3,4.7,1.2,11.2' };
const LAYER_KINDS = ['government_acquisition', 'forest_reserve', 'road_reserve', 'waterway', 'wetland', 'flood_zone', 'known_dispute', 'planning_zone', 'other'];

function AreaMap() {
  const router = useRouter();
  const layers = useGet<Page<Layer>>('/v1/admin/overlay-layers', { country: 'GH' });
  const [area, setArea] = useState('Accra sample area');
  const [on, setOn] = useState<string[] | null>(null);
  const active = (layers.data?.items ?? []).filter((l) => l.status === 'active');
  const codes = on ?? active.map((l) => l.code);
  const map = useGet<FC>('/v1/geo/map', { country: 'GH', bbox: AREAS[area], ...(codes.length ? { layers: codes.join(',') } : {}) });
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Area"><Select value={area} onChange={(e) => setArea(e.target.value)}>{Object.keys(AREAS).map((a) => <option key={a}>{a}</option>)}</Select></Field>
      </div>
      <div className="row" style={{ gap: 6 }} role="group" aria-label="Layers">
        {active.map((l) => {
          const sel = codes.includes(l.code);
          return <button key={l.id} type="button" className={`btn btn-sm ${sel ? 'btn-dark' : 'btn-ghost'}`} style={{ minHeight: 44 }} aria-pressed={sel} onClick={() => setOn(sel ? codes.filter((c) => c !== l.code) : [...codes, l.code])}>{l.name}</button>;
        })}
      </div>
      <ProblemBox error={map.error} />
      {map.isLoading ? <Skeleton lines={6} /> : <GeoMap data={map.data} onSelect={(f) => { if (f.properties.asset_id) router.push(`/geo/assets/${f.properties.asset_id}`); }} />}
      {active.some((l) => l.is_sample) ? <p className="muted" style={{ margin: 0, fontSize: 13 }}>Layers marked sample are drawn for demonstration. They are not a real map.</p> : null}
    </div>
  );
}

function Assets() {
  const [q, setQ] = useState('');
  const [disputed, setDisputed] = useState('');
  const list = useGet<Page<Asset>>('/v1/assets', { limit: 100, ...(q ? { q } : {}), ...(disputed ? { disputed_flag: disputed } : {}) });
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Reference, locality, plot number, GPS" /></Field>
        <Field label="Disputed"><Select value={disputed} onChange={(e) => setDisputed(e.target.value)}><option value="">All</option><option value="true">Disputed only</option><option value="false">Not disputed</option></Select></Field>
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={5} /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((a) => (
            <Link key={a.id} href={`/geo/assets/${a.id}`} className="rowlink">
              <div className="main"><div className="mono" style={{ fontSize: 12 }}>{a.reference} · {words(a.type)}</div><div className="title">{a.name || a.locality || a.address || 'Property'}</div><div className="meta">{a.owner_name || 'No owner'} · {[a.locality, a.region].filter(Boolean).join(', ')}{a.current_boundary ? ` · boundary v${a.current_boundary.version}, ${a.current_boundary.area_acres} acres` : ' · no boundary yet'}</div></div>
              <div className="row" style={{ gap: 6 }}>
                {a.disputed_flag ? <span className="chip chip-ink">! Disputed</span> : null}
                {a.verified_at ? <span className="chip chip-lime">✓ Verified</span> : null}
                {a.open_alerts ? <span className="chip">{a.open_alerts} alert{a.open_alerts > 1 ? 's' : ''}</span> : null}
              </div>
            </Link>
          ))}
        </div>
      ) : <Empty>No properties match.</Empty>}
    </div>
  );
}

function Overlaps() {
  const [status, setStatus] = useState('open');
  const list = useGet<Page<Overlap>>('/v1/overlap-flags', { status });
  return (
    <div className="stack">
      <div className="filters"><Field label="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}>{['open', 'confirmed', 'dismissed'].map((s) => <option key={s} value={s}>{words(s)}</option>)}</Select></Field></div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((o) => (
            <div key={o.id} className="rowlink">
              <div className="main">
                <div className="title"><Link href={`/geo/assets/${o.asset}`}>{o.asset_reference}</Link> overlaps <Link href={`/geo/assets/${o.other_asset?.id}`}>{o.other_asset?.reference}</Link></div>
                <div className="meta">{Number(o.overlap_area_sqm).toFixed(0)} m² · {(Number(o.overlap_share) * 100).toFixed(0)}% of this plot · the other is {words(o.other_kind).toLowerCase()} ({o.other_asset?.owner_name}, {o.other_asset?.locality}) · {day(o.created_at)}</div>
                {o.resolution_note ? <div className="meta">{words(o.resolution)}: {o.resolution_note} · {o.resolved_by_name}</div> : null}
              </div>
              {o.status === 'open' ? (
                <ActionForm label="Decide" variant="dark" path={`/v1/overlap-flags/${o.id}/resolve`} fields={[
                  { name: 'outcome', label: 'Outcome', type: 'select', required: true, options: [{ value: 'confirmed', label: 'Confirmed: the plots overlap' }, { value: 'dismissed', label: 'Dismissed: no real overlap' }] },
                  { name: 'note', label: 'What you found', type: 'textarea', required: true },
                ]} onDone={() => list.mutate()} submitLabel="Save" />
              ) : <span className="chip">{words(o.status)}</span>}
            </div>
          ))}
        </div>
      ) : <Empty>No overlaps in this list.</Empty>}
    </div>
  );
}

function Alerts() {
  const { client, hasRole } = useSession();
  const [status, setStatus] = useState('open');
  const list = useGet<Page<Alert>>('/v1/monitoring-alerts', { status });
  const act = useAct();
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}>{['open', 'in_review', 'resolved'].map((s) => <option key={s} value={s}>{words(s)}</option>)}</Select></Field>
        {hasRole('CM', 'RV') ? <Button variant="ghost" busy={act.busy} onClick={() => act.run(() => call<{ checked: number; alerts: number }>(client, 'POST', '/v1/monitoring/runs', { country: 'GH' }).then((r) => { list.mutate(); act.show(`${r.checked} plots compared, ${r.alerts} new alerts.`); }))}>Compare imagery now</Button> : null}
      </div>
      <ProblemBox error={list.error ?? act.error} />
      {list.isLoading ? <Skeleton /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((a) => (
            <div key={a.id} className="rowlink">
              <div className="main">
                <div className="title"><Link href={`/geo/assets/${a.asset}`}>{a.asset_reference}</Link>: {words(a.change_kind)}</div>
                <div className="meta">Change score {a.change_score} (threshold {a.threshold}) · {day(a.previous_date)} → {day(a.new_date)}{a.assigned_to_name ? ` · ${a.assigned_to_name}` : ''}{a.resolution_note ? ` · ${words(a.resolution)}: ${a.resolution_note}` : ''}</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <span className="chip">{words(a.status)}</span>
                {a.status === 'open' ? <Button size="sm" variant="ghost" onClick={() => act.run(() => call(client, 'POST', `/v1/monitoring-alerts/${a.id}/review`).then(() => list.mutate()), 'Taken for review.')}>Take</Button> : null}
                {a.status !== 'resolved' ? (
                  <ActionForm label="Resolve" variant="dark" path={`/v1/monitoring-alerts/${a.id}/resolve`} upload={{ subject_type: 'asset', subject_id: a.asset, role: 'monitoring_check' }} fields={[
                    { name: 'resolution', label: 'What it was', type: 'select', required: true, options: [{ value: 'no_change', label: 'No real change' }, { value: 'change_explained', label: 'Change explained' }, { value: 'change_confirmed', label: 'Change confirmed' }] },
                    { name: 'note', label: 'Note', type: 'textarea', required: true }, { name: 'evidence_id', label: 'Evidence (site photo, owner message)', type: 'file' },
                  ]} body={(v) => ({ resolution: v.resolution, note: v.note, ...(v.evidence_id ? { evidence_id: v.evidence_id } : {}) })} onDone={() => list.mutate()} submitLabel="Save" />
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : <Empty>No alerts in this list.</Empty>}
      {act.toast}
    </div>
  );
}

function Layers() {
  const { hasRole } = useSession();
  const list = useGet<Page<Layer>>('/v1/admin/overlay-layers', { country: 'GH' });
  return (
    <div className="stack">
      {hasRole('AD') ? (
        <div><ActionForm label="+ New layer" variant="dark" path="/v1/admin/overlay-layers" fields={[
          { name: 'code', label: 'Code (letters, numbers, dashes)', required: true }, { name: 'name', label: 'Name', required: true },
          { name: 'kind', label: 'Kind', type: 'select', required: true, options: LAYER_KINDS.map((k) => ({ value: k, label: words(k) })) },
          { name: 'description', label: 'Description', type: 'textarea' }, { name: 'buffer_m', label: 'Buffer in metres (empty: country setting)', type: 'number' },
          { name: 'is_sample', label: 'Sample data, not a real map', type: 'checkbox' },
        ]} body={(v) => ({ country: 'GH', code: v.code, name: v.name, kind: v.kind, description: v.description || '', is_sample: !!v.is_sample, ...(v.buffer_m ? { buffer_m: v.buffer_m } : {}) })} onDone={() => list.mutate()} submitLabel="Create" /></div>
      ) : null}
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((l) => (
            <Link key={l.id} href={`/geo/layers/${l.id}`} className="rowlink">
              <div className="main"><div className="mono" style={{ fontSize: 12 }}>{l.code}</div><div className="title">{l.name}</div><div className="meta">{words(l.kind)} · buffer {l.effective_buffer_m} m · {l.current_version ? `v${l.current_version.version}, ${l.current_version.feature_count} features, from ${dayTime(l.current_version.created_at)}` : 'no version loaded'}</div></div>
              <div className="row" style={{ gap: 6 }}>{l.is_sample ? <span className="chip">Sample</span> : null}<span className="chip">{words(l.status)}</span></div>
            </Link>
          ))}
        </div>
      ) : <Empty>No overlay layers.</Empty>}
    </div>
  );
}

function GeoHome() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get('tab') ?? 'map';
  const TABS = [{ key: 'map', label: 'Map' }, { key: 'assets', label: 'Properties' }, { key: 'overlaps', label: 'Overlaps' }, { key: 'alerts', label: 'Monitoring alerts' }, { key: 'layers', label: 'Overlay layers' }];
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head title="Maps and layers" sub="Every plot is checked against each overlay layer when its boundary is saved, and against earlier plots." />
      <div className="tabs-scroll"><Tabs items={TABS} current={tab} onChange={(k) => router.replace(`/geo?tab=${k}`)} /></div>
      {tab === 'map' ? <AreaMap /> : tab === 'assets' ? <Assets /> : tab === 'overlaps' ? <Overlaps /> : tab === 'alerts' ? <Alerts /> : <Layers />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton />}><GeoHome /></Suspense>;
}
