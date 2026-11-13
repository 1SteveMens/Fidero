'use client';
/* One property on the map: the boundary and its versions (FR-GEO-001), overlay results per layer with the proposed
 * section 7 verdict (FR-GEO-002, FR-GEO-003), overlaps with earlier plots (FR-GEO-005), satellite images
 * (FR-GEO-006), monitoring (FR-GEO-007) and the disputed flag (RUL-17). */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, Button, call, Empty, ProblemBox, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, Facts, Head, Panel, useAct, words } from '@/components/core/kit';
import { GeoMap, type FC } from '@/components/core/GeoMap';
import type { Asset } from '@/components/core/types';

type Run = { id: string; boundary_version: number; status: string; trigger: string; proposed_verdict: string | null; verdict_reasons: { verdict: string; layer: string; message: string }[]; layers_expected: number; layers_checked: number; items: { layer_id: string; layer_name: string; layer_kind: string; is_sample: boolean; layer_version?: number; status: string; outcome?: string; message?: string }[]; completed_at: string | null; created_at: string };
type Section7 = { boundary_id: string | null; proposed_verdict: string | null; status: string; reasons: { verdict: string; layer: string; message: string }[]; run: Run | null; history: Run[] };
type Boundary = { id: string; version: number; source: string; area_sqm: string; area_acres: string; perimeter_m: string; point_count: number; note: string; captured_by_name: string; is_current: boolean; created_at: string };
type Overlap = { id: string; other_asset: { id: string; reference: string; locality: string; owner_name: string } | null; other_kind: string; overlap_area_sqm: string; overlap_share: string; status: string; resolution_note: string };
type Image = { id: string; purpose: string; status: string; provider: string; captured_on: string | null; cloud_cover: string | null; gap_reason: string; content_url: string; created_at: string };
type Enrolment = { id: string; reason: string; status: string; baseline_date: string | null; last_checked_at: string | null; ended_reason: string; created_at: string };

const OUT: Record<string, string> = { inside: '✕ Inside', near: '! Near', clear: '✓ Clear' };

export default function AssetPage() {
  const { id } = useParams<{ id: string }>();
  const { client, hasRole } = useSession();
  const a = useGet<Asset>(`/v1/assets/${id}`);
  const map = useGet<FC>(`/v1/assets/${id}/map`);
  const s7 = useGet<Section7>(`/v1/assets/${id}/overlay-results`, undefined, { shouldRetryOnError: false });
  const bounds = useGet<Boundary[]>(`/v1/assets/${id}/boundaries`);
  const overlaps = useGet<Overlap[]>(hasRole('CM', 'RV', 'AD', 'AN') ? `/v1/assets/${id}/overlaps` : null, undefined, { shouldRetryOnError: false });
  const images = useGet<Image[]>(`/v1/assets/${id}/satellite-images`);
  const enrol = useGet<Enrolment[]>(`/v1/assets/${id}/monitoring`);
  const act = useAct();
  const staff = hasRole('CM', 'RV');
  if (a.isLoading) return <Skeleton lines={8} />;
  if (!a.data) return <ProblemBox error={a.error ?? 'Property not found.'} />;
  const x = a.data;
  const reload = () => { a.mutate(); map.mutate(); s7.mutate(); bounds.mutate(); overlaps.mutate(); };
  const run = s7.data?.run;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/geo?tab=assets', label: 'Maps and layers' }} title={<><span className="mono" style={{ fontSize: '0.55em', display: 'block' }}>{x.reference}</span>{x.name || x.locality || 'Property'}</>}
        chips={<><span className="chip">{words(x.type)}</span>{x.disputed_flag ? <span className="chip chip-ink">! Disputed</span> : null}{x.verified_at ? <span className="chip chip-lime">✓ Verified {day(x.verified_at)}</span> : null}{x.monitoring_active ? <span className="chip">Watched</span> : null}</>}
        sub={<>{x.owner_name || 'No owner'} · {[x.plot_number && `plot ${x.plot_number}`, x.locality, x.district, x.region].filter(Boolean).join(', ')}</>}
        actions={staff ? <>
          <ActionForm label={x.disputed_flag ? 'Clear disputed flag' : 'Mark disputed'} path={`/v1/assets/${id}/disputed-flag`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: !x.disputed_flag }]}
            body={(v) => ({ disputed: !x.disputed_flag, reason: v.reason || '' })} onDone={reload} submitLabel="Save" intro="A disputed plot needs two people on any site visit (RUL-17)." />
          <ActionForm label="Fresh-search case" path={`/v1/assets/${id}/fresh-searches`} fields={[{ name: 'reason', label: 'Why', type: 'textarea' }]} onDone={(out) => { const c = out as { id?: string }; if (c?.id) window.location.href = `/cases/${c.id}`; }} submitLabel="Open case" intro="Repeats the official search and a site check before purchase money is released (RUL-07)." />
        </> : null} />
      {x.disputed_flag ? <Blocked title="Disputed plot">{x.disputed_reason || 'Two people on any visit.'}</Blocked> : null}
      <ProblemBox error={act.error} />
      <div className="cols">
        <Panel title="Map">
          {map.isLoading ? <Skeleton lines={6} /> : <GeoMap data={map.data} selected={x.id} />}
          {x.current_boundary ? <Facts items={[['Boundary', `v${x.current_boundary.version}, ${words(x.current_boundary.source).toLowerCase()}`], ['Area', `${Number(x.current_boundary.area_sqm).toFixed(0)} m² (${x.current_boundary.area_acres} acres)`], ['Perimeter', `${Number(x.current_boundary.perimeter_m).toFixed(0)} m`]]} /> : <p className="muted" style={{ margin: 0 }}>No boundary saved yet.</p>}
        </Panel>
        <Panel title="Overlay checks" actions={staff && x.current_boundary ? <Button size="sm" variant="ghost" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/assets/${id}/overlay-checks`).then(reload), 'Checks run again.')}>Run again</Button> : null}>
          {s7.isLoading ? <Skeleton /> : s7.data ? (
            <>
              <div><strong>Proposed for report section 7: {s7.data.proposed_verdict ? words(s7.data.proposed_verdict) : 'none yet'}</strong> <span className="muted">({words(s7.data.status).toLowerCase()}). The lawyer decides.</span></div>
              {s7.data.reasons.map((r, i) => <div key={i} style={{ fontSize: 14 }}>{words(r.verdict)}: {r.message}</div>)}
              {run ? (
                <div className="rows">
                  {run.items.map((it) => (
                    <div key={it.layer_id} className="rowlink">
                      <div className="main"><div className="title">{it.layer_name}{it.is_sample ? ' (sample)' : ''}</div><div className="meta">{words(it.layer_kind)}{it.layer_version ? ` · layer v${it.layer_version}` : ''}{it.message ? ` · ${it.message}` : ''}</div></div>
                      <span className={`chip ${it.outcome === 'clear' ? 'chip-lime' : it.outcome === 'inside' ? 'chip-ink' : ''}`}>{it.outcome ? OUT[it.outcome] ?? words(it.outcome) : words(it.status)}</span>
                    </div>
                  ))}
                </div>
              ) : null}
              {run ? <div className="mono muted" style={{ fontSize: 12 }}>Boundary v{run.boundary_version} · {run.layers_checked} of {run.layers_expected} layers · {dayTime(run.completed_at ?? run.created_at)} · {words(run.trigger)}</div> : null}
              {s7.data.history.length ? <details><summary style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}>Earlier runs ({s7.data.history.length})</summary>
                <div className="rows">{s7.data.history.map((h) => <div key={h.id} className="rowlink"><div className="main"><div className="meta mono">{dayTime(h.created_at)} · boundary v{h.boundary_version} · {words(h.trigger)}</div></div><span className="chip">{h.proposed_verdict ? words(h.proposed_verdict) : words(h.status)}</span></div>)}</div></details> : null}
            </>
          ) : <p className="muted" style={{ margin: 0 }}>Only staff and the assigned professionals see overlay results.</p>}
        </Panel>
      </div>

      <Panel title="Boundary versions" actions={staff ? (
        <ActionForm label="Save a new boundary" variant="dark" path={`/v1/assets/${id}/boundary`} method="PUT" upload={{ subject_type: 'asset', subject_id: id, role: 'site_plan' }} fields={[
          { name: 'source', label: 'Source', type: 'select', required: true, options: ['surveyor_coordinates', 'digitised_site_plan', 'geojson_upload', 'drawn'].map((s) => ({ value: s, label: words(s) })) },
          { name: 'coordinates', label: 'Corner points, one "x, y" per line (surveyor coordinates)', type: 'textarea' },
          { name: 'srid', label: 'Coordinate system (EPSG code)', initial: '4326', hint: 'For example 4326 (longitude, latitude), 2136 or 25000.' },
          { name: 'geojson', label: 'Or paste GeoJSON (Polygon or Feature)', type: 'textarea' },
          { name: 'evidence_id', label: "Surveyor's file or site plan", type: 'file' }, { name: 'note', label: 'Note' },
        ]} body={(v) => {
          const coords = String(v.coordinates || '').split('\n').map((l) => l.split(/[,\s]+/).filter(Boolean).map(Number)).filter((p) => p.length >= 2 && p.every((n) => !Number.isNaN(n)));
          if (coords.length && (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1])) coords.push(coords[0]);
          let gj: unknown;
          if (v.geojson) { try { gj = JSON.parse(String(v.geojson)); } catch { throw new Error('The GeoJSON is not valid JSON.'); } }
          return { source: v.source, ...(coords.length ? { coordinates: coords, srid: Number(v.srid) || 4326 } : {}), ...(gj ? { geojson: gj } : {}), ...(v.evidence_id ? { evidence_id: v.evidence_id } : {}), note: v.note || '' };
        }} onDone={reload} submitLabel="Save and check" intro="The old version is kept. Overlay and overlap checks run on save." />
      ) : null}>
        {bounds.isLoading ? <Skeleton /> : bounds.data?.length ? (
          <div className="rows">
            {bounds.data.map((b) => (
              <div key={b.id} className="rowlink">
                <div className="main"><div className="title">Version {b.version}{b.is_current ? ' (current)' : ''}</div><div className="meta">{words(b.source)} · {b.point_count} points · {Number(b.area_sqm).toFixed(0)} m² · {b.captured_by_name} · {dayTime(b.created_at)}{b.note ? ` · ${b.note}` : ''}</div></div>
              </div>
            ))}
          </div>
        ) : <Empty>No boundary versions.</Empty>}
      </Panel>

      <div className="grid2">
        <Panel title="Overlaps with other plots">
          {overlaps.data?.length ? (
            <div className="rows">
              {overlaps.data.map((o) => (
                <div key={o.id} className="rowlink">
                  <div className="main"><div className="title">{o.other_asset ? <Link href={`/geo/assets/${o.other_asset.id}`}>{o.other_asset.reference}</Link> : 'Another plot'}</div><div className="meta">{Number(o.overlap_area_sqm).toFixed(0)} m² · {(Number(o.overlap_share) * 100).toFixed(0)}% · {words(o.other_kind).toLowerCase()} · {o.other_asset?.owner_name}{o.resolution_note ? ` · ${o.resolution_note}` : ''}</div></div>
                  {o.status === 'open' && staff ? <ActionForm label="Decide" variant="dark" path={`/v1/overlap-flags/${o.id}/resolve`} fields={[{ name: 'outcome', label: 'Outcome', type: 'select', required: true, options: [{ value: 'confirmed', label: 'Confirmed' }, { value: 'dismissed', label: 'Dismissed' }] }, { name: 'note', label: 'What you found', type: 'textarea', required: true }]} onDone={reload} submitLabel="Save" /> : <span className="chip">{words(o.status)}</span>}
                </div>
              ))}
            </div>
          ) : <p className="muted" style={{ margin: 0 }}>{overlaps.error ? 'Staff only.' : 'No overlap found.'}</p>}
        </Panel>
        <Panel title="Satellite and monitoring" actions={staff ? <>
          <ActionForm label="Fetch image" path={`/v1/assets/${id}/satellite-images`} fields={[{ name: 'purpose', label: 'For', type: 'select', initial: 'on_request', options: [{ value: 'on_request', label: 'A check now' }, { value: 'report', label: 'The report' }, { value: 'monitoring', label: 'Monitoring' }] }]} onDone={() => images.mutate()} submitLabel="Fetch" />
          {!x.monitoring_active ? <ActionForm label="Start watching" path={`/v1/assets/${id}/monitoring`} body={() => ({ reason: 'manual' })} onDone={() => { enrol.mutate(); a.mutate(); }} submitLabel="Start" intro="New imagery is compared on a schedule; changes raise an alert." /> : null}
        </> : null}>
          {images.data?.length ? (
            <div className="row" style={{ gap: 10 }}>
              {images.data.slice(0, 4).map((im) => (
                <figure key={im.id} style={{ margin: 0, width: 150 }}>
                  {im.status === 'available' ? <img src={im.content_url} alt={`Satellite image ${im.captured_on ?? ''}`} style={{ width: 150, height: 150, objectFit: 'cover', borderRadius: 12, background: '#e9e6df' }} /> : <div className="card" style={{ height: 150, display: 'grid', placeItems: 'center', fontSize: 13 }}>{im.gap_reason || words(im.status)}</div>}
                  <figcaption className="mono" style={{ fontSize: 11 }}>{day(im.captured_on)} · {words(im.purpose)}{im.cloud_cover ? ` · ${im.cloud_cover}% cloud` : ''}</figcaption>
                </figure>
              ))}
            </div>
          ) : <p className="muted" style={{ margin: 0 }}>No satellite image yet.</p>}
          {enrol.data?.length ? enrol.data.map((en) => (
            <div key={en.id} className="rowlink">
              <div className="main"><div className="title">{words(en.reason)} watch</div><div className="meta">Baseline {day(en.baseline_date)} · last compared {dayTime(en.last_checked_at)}{en.ended_reason ? ` · ended: ${en.ended_reason}` : ''}</div></div>
              {en.status === 'active' && staff ? <ActionForm label="Stop" path={`/v1/monitoring/enrolments/${en.id}/end`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={() => { enrol.mutate(); a.mutate(); }} submitLabel="Stop watching" /> : <span className="chip">{words(en.status)}</span>}
            </div>
          )) : null}
          {x.open_alerts ? <Link className="btn btn-ghost btn-sm" href="/geo?tab=alerts">{x.open_alerts} open alert{x.open_alerts > 1 ? 's' : ''}</Link> : null}
        </Panel>
      </div>
      {act.toast}
    </div>
  );
}
