'use client';
/* One overlay layer (FR-GEO-004): its versions (the old ones are kept so earlier results stay traceable), uploading a
 * new version, switching it on or off, its features on the map and re-checking plots against it. */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, call, Empty, Field, ProblemBox, Select, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, Facts, Head, Panel, useAct, words } from '@/components/core/kit';
import { GeoMap, type FC } from '@/components/core/GeoMap';

type Layer = { id: string; code: string; name: string; kind: string; description: string; buffer_m: string | null; effective_buffer_m: string; status: string; is_sample: boolean; current_version: { id: string; version: number } | null; updated_at: string };
type Version = { id: string; version: number; status: string; source: string; source_format: string; input_srid: number; valid_from: string | null; feature_count: number; sha256: string; note: string; loaded_by_name: string; created_at: string };

export default function LayerPage() {
  const { id } = useParams<{ id: string }>();
  const { client, hasRole } = useSession();
  const layer = useGet<Layer>(`/v1/admin/overlay-layers/${id}`);
  const versions = useGet<Version[]>(`/v1/admin/overlay-layers/${id}/versions`);
  const [v, setV] = useState('');
  const feats = useGet<FC>(`/v1/admin/overlay-layers/${id}/features`, v ? { version: v } : {}, { shouldRetryOnError: false });
  const act = useAct();
  if (layer.isLoading) return <Skeleton lines={6} />;
  if (!layer.data) return <ProblemBox error={layer.error ?? 'Layer not found.'} />;
  const l = layer.data;
  const admin = hasRole('AD');
  const reload = () => { layer.mutate(); versions.mutate(); feats.mutate(); };
  const mapData: FC | undefined = feats.data ? { type: 'FeatureCollection', features: feats.data.features.map((f) => ({ ...f, properties: { ...f.properties, kind: 'layer' } })) } : undefined;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/geo?tab=layers', label: 'Overlay layers' }} title={l.name} chips={<><span className="chip">{words(l.kind)}</span><span className="chip">{words(l.status)}</span>{l.is_sample ? <span className="chip">Sample, not a real map</span> : null}</>}
        sub={l.description}
        actions={<>
          {admin ? <ActionForm label={l.status === 'active' ? 'Switch off' : 'Switch on'} path={`/v1/admin/overlay-layers/${id}/status`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea' }]} body={(x) => ({ status: l.status === 'active' ? 'retired' : 'active', reason: x.reason || '' })} onDone={reload} submitLabel="Save" /> : null}
          {admin ? <ActionForm label="Edit" path={`/v1/admin/overlay-layers/${id}`} method="PATCH" fields={[{ name: 'name', label: 'Name', initial: l.name }, { name: 'description', label: 'Description', type: 'textarea', initial: l.description }, { name: 'buffer_m', label: 'Buffer in metres (empty: country setting)', type: 'number', initial: l.buffer_m ?? '' }]}
            body={(x) => ({ name: x.name, description: x.description, buffer_m: x.buffer_m ? x.buffer_m : null })} onDone={reload} submitLabel="Save" /> : null}
          {hasRole('CM', 'RV') ? <Button size="sm" variant="ghost" busy={act.busy} onClick={() => act.run(() => call<{ runs: unknown[] }>(client, 'POST', `/v1/admin/overlay-layers/${id}/rechecks`, {}).then((r) => act.show(`${r.runs.length} plots re-checked.`)))}>Re-check plots</Button> : null}
        </>} />
      <ProblemBox error={act.error} />
      <Facts items={[['Code', <span key="c" className="mono">{l.code}</span>], ['Buffer', `${l.effective_buffer_m} m${l.buffer_m ? '' : ' (country setting)'}`], ['Current version', l.current_version ? `v${l.current_version.version}` : 'none'], ['Updated', dayTime(l.updated_at)]]} />
      <div className="cols">
        <Panel title="Features" actions={versions.data?.length ? (
          <Field label="Version"><Select value={v} onChange={(e) => setV(e.target.value)}><option value="">Current</option>{versions.data.map((x) => <option key={x.id} value={String(x.version)}>v{x.version}</option>)}</Select></Field>
        ) : null}>
          {feats.isLoading ? <Skeleton lines={5} /> : <GeoMap data={mapData} />}
        </Panel>
        <Panel title="Versions" actions={admin ? (
          <ActionForm label="Upload a version" variant="dark" path={`/v1/admin/overlay-layers/${id}/versions`} fields={[
            { name: 'source', label: 'Who published the map and which edition', required: true },
            { name: 'geojson', label: 'GeoJSON FeatureCollection of polygons', type: 'textarea', required: true },
            { name: 'valid_from', label: 'Valid from', type: 'date' }, { name: 'srid', label: 'Coordinate system (EPSG)', initial: '4326' },
            { name: 'note', label: 'Note' }, { name: 'recheck', label: 'Re-check unverified plots against it now', type: 'checkbox' },
          ]} body={(x) => { let gj: unknown; try { gj = JSON.parse(String(x.geojson)); } catch { throw new Error('The GeoJSON is not valid JSON.'); } return { source: x.source, geojson: gj, valid_from: x.valid_from || null, srid: Number(x.srid) || 4326, note: x.note || '', recheck: !!x.recheck }; }}
            onDone={reload} submitLabel="Upload" intro="The old version is kept, so earlier results stay traceable." />
        ) : null}>
          {versions.isLoading ? <Skeleton /> : versions.data?.length ? (
            <div className="rows">
              {versions.data.map((x) => (
                <div key={x.id} className="rowlink">
                  <div className="main"><div className="title">v{x.version} · {x.feature_count} features</div><div className="meta">{x.source} · valid from {day(x.valid_from)} · {x.loaded_by_name} · {dayTime(x.created_at)}</div><div className="meta mono">sha256 {x.sha256.slice(0, 16)}…</div></div>
                  <span className="chip">{words(x.status)}</span>
                </div>
              ))}
            </div>
          ) : <Empty>No versions loaded.</Empty>}
        </Panel>
      </div>
      {act.toast}
    </div>
  );
}
