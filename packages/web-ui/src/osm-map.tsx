'use client';
/* A map on OpenStreetMap tiles (Leaflet) for the portal and the back office.
 * Tiles are not reachable from every network (offices, some mobile data, the
 * build machines). When no tile has loaded after a few seconds, or one fails
 * before any loads, the map gives way to `fallback`: the plain SVG drawing each
 * screen already has. OpenStreetMap is credited on the map, as its licence asks. */
import React, { useEffect, useRef, useState } from 'react';
import type * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export type LngLat = { lng: number; lat: number };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Props = Record<string, any>;
export type MapFeature = { type: 'Feature'; id?: string | number; geometry: { type: string; coordinates: unknown }; properties: Props };
export type MapFeatures = { type: 'FeatureCollection'; features: MapFeature[] };

export type FeatureLook = { fill: string; stroke: string; fillOpacity?: number; dash?: string; weight?: number; radius?: number };

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const GIVE_UP_MS = 6000;

export function OsmMap({
  features, look, title, onFeatureClick, fallback, height, centre, zoom = 17, drawing, label, after,
}: {
  features?: MapFeatures | null;
  /** Bloc colours by meaning, per feature. Default: a lime plot with an ink outline. */
  look?: (f: MapFeature) => FeatureLook;
  title?: (f: MapFeature) => string;
  onFeatureClick?: (f: MapFeature) => void;
  /** What to show when tiles cannot be loaded. */
  fallback: React.ReactNode;
  height?: number | string;
  /** Where to look when there are no features (and where drawing starts). */
  centre?: LngLat;
  zoom?: number;
  /** Tap the map to add the corners of a plot. */
  drawing?: { points: LngLat[]; onAdd: (p: LngLat) => void };
  label: string;
  /** Shown under the map only while the tiles are in use (the fallback brings its own). */
  after?: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const lib = useRef<typeof L | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'failed'>(() => (typeof navigator !== 'undefined' && navigator.onLine === false ? 'failed' : 'loading'));
  const addRef = useRef(drawing?.onAdd);
  addRef.current = drawing?.onAdd;
  const clickRef = useRef(onFeatureClick);
  clickRef.current = onFeatureClick;

  // Create the map once.
  useEffect(() => {
    if (state === 'failed' || !box.current || map.current) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    import('leaflet').then((mod) => {
      const Lf = ((mod as unknown as { default?: typeof L }).default ?? mod) as typeof L;
      if (cancelled || !box.current) return;
      lib.current = Lf;
      const m = Lf.map(box.current, { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
      m.attributionControl.setPrefix(false);
      let loaded = false;
      const tiles = Lf.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTRIBUTION, crossOrigin: true });
      tiles.on('tileload', () => { if (!loaded) { loaded = true; setState('ok'); } });
      tiles.on('tileerror', () => { if (!loaded) setState('failed'); });
      tiles.addTo(m);
      timer = setTimeout(() => { if (!loaded) setState('failed'); }, GIVE_UP_MS);
      m.on('click', (e: L.LeafletMouseEvent) => addRef.current?.({ lng: +e.latlng.lng.toFixed(7), lat: +e.latlng.lat.toFixed(7) }));
      layer.current = Lf.layerGroup().addTo(m);
      map.current = m;
      if (centre) m.setView([centre.lat, centre.lng], zoom);
      else m.setView([0, 0], 2);
      draw();
    }).catch(() => setState('failed'));
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => { map.current?.remove(); map.current = null; }, []);
  useEffect(() => { if (state === 'failed') { map.current?.remove(); map.current = null; } }, [state]);

  // Draw (and redraw) the features and the corners being drawn.
  function draw() {
    const Lf = lib.current; const m = map.current; const g = layer.current;
    if (!Lf || !m || !g) return;
    g.clearLayers();
    const bounds: L.LatLngExpression[] = [];
    for (const f of features?.features ?? []) {
      const lk = look?.(f) ?? { fill: '#a3ee5b', stroke: '#0b0b0b' };
      const style = { color: lk.stroke, weight: lk.weight ?? 2, fillColor: lk.fill, fillOpacity: lk.fillOpacity ?? 0.6, dashArray: lk.dash };
      const gj = Lf.geoJSON(f as unknown as GeoJSON.Feature, {
        style: () => style,
        pointToLayer: (_p, ll) => Lf.circleMarker(ll, { ...style, radius: lk.radius ?? 9, fillOpacity: lk.fillOpacity ?? 0.95 }),
      });
      const t = title?.(f);
      if (t) gj.bindTooltip(t);
      gj.on('click', (e: L.LeafletMouseEvent) => { Lf.DomEvent.stopPropagation(e); clickRef.current?.(f); });
      gj.addTo(g);
      const b = gj.getBounds();
      if (b.isValid()) bounds.push(b.getSouthWest(), b.getNorthEast());
    }
    const pts = drawing?.points ?? [];
    if (pts.length >= 3) Lf.polygon(pts.map((p) => [p.lat, p.lng] as [number, number]), { color: '#0b0b0b', weight: 2, fillColor: '#a3ee5b', fillOpacity: 0.35 }).addTo(g);
    else if (pts.length === 2) Lf.polyline(pts.map((p) => [p.lat, p.lng] as [number, number]), { color: '#0b0b0b', weight: 2 }).addTo(g);
    pts.forEach((p, i) => Lf.circleMarker([p.lat, p.lng], { radius: 7, color: '#0b0b0b', weight: 2, fillColor: '#a3ee5b', fillOpacity: 1 })
      .bindTooltip(String(i + 1), { permanent: true, direction: 'top', offset: [0, -6] }).addTo(g));
    if (bounds.length && !drawing) m.fitBounds(Lf.latLngBounds(bounds), { padding: [24, 24], maxZoom: 18 });
  }
  useEffect(draw, [features, drawing?.points]); // eslint-disable-line react-hooks/exhaustive-deps

  if (state === 'failed') return <>{fallback}</>;
  const mapBox = (
    <div
      ref={box}
      className="osm-map"
      role={drawing ? 'application' : 'region'}
      aria-label={label}
      aria-busy={state === 'loading' || undefined}
      style={{ height: height ?? undefined }}
    />
  );
  return after ? <div className="stack" style={{ gap: 8 }}>{mapBox}{after}</div> : mapBox;
}
