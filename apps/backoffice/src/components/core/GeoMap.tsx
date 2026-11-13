'use client';
/* Plain SVG map of GeoJSON (the tile host is not reachable from every network, so no tiles are needed).
 * Plots in lime with an ink outline; overlay layers in neutral greys told apart by pattern; overlapping plots
 * hatched in ink. No red, orange or yellow: those colours keep their meanings (6.1a). Zoom with the buttons;
 * drag to pan. */
import { useMemo, useRef, useState } from 'react';

type Geometry = { type: string; coordinates: unknown };
export type Feature = { type: 'Feature'; id?: string | number; geometry: Geometry; properties: Record<string, unknown> };
export type FC = { type: 'FeatureCollection'; features: Feature[] };

const LAYER_STYLE: Record<string, { fill: string; stroke: string; dash?: string; label: string }> = {
  forest_reserve: { fill: 'url(#p-dots)', stroke: '#3a3a3a', label: 'Forest reserve' },
  waterway: { fill: '#c9d3d6', stroke: '#5b6b70', label: 'Waterway' },
  wetland: { fill: '#c9d3d6', stroke: '#5b6b70', dash: '4 3', label: 'Wetland' },
  flood_zone: { fill: '#d6dadb', stroke: '#5b6b70', dash: '2 2', label: 'Flood zone' },
  road_reserve: { fill: '#d9d6cf', stroke: '#6a675f', dash: '6 3', label: 'Road reserve' },
  government_acquisition: { fill: 'url(#p-lines)', stroke: '#0b0b0b', label: 'Government acquisition' },
  known_dispute: { fill: 'url(#p-cross)', stroke: '#0b0b0b', dash: '3 3', label: 'Known dispute area' },
  planning_zone: { fill: '#e2dfd7', stroke: '#6a675f', label: 'Planning zone' },
  other: { fill: '#e2dfd7', stroke: '#6a675f', label: 'Other layer' },
};

function rings(g: Geometry): number[][][] {
  const c = g.coordinates as unknown;
  if (g.type === 'Polygon') return c as number[][][];
  if (g.type === 'MultiPolygon') return (c as number[][][][]).flat();
  if (g.type === 'LineString') return [c as number[][]];
  if (g.type === 'MultiLineString') return c as number[][][];
  return [];
}

function points(g: Geometry): number[][] {
  if (g.type === 'Point') return [g.coordinates as number[]];
  return rings(g).flat();
}

export function GeoMap({ data, onSelect, selected, height }: { data?: FC | null; onSelect?: (f: Feature) => void; selected?: string | null; height?: number }) {
  const feats = useMemo(() => data?.features ?? [], [data]);
  const ext = useMemo(() => {
    const pts = feats.flatMap((f) => points(f.geometry));
    if (!pts.length) return null;
    const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1]);
    return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  }, [feats]);
  const W = 800; const H = 600;
  const proj = useMemo(() => {
    if (!ext) return null;
    const k = Math.cos(((ext.minY + ext.maxY) / 2) * Math.PI / 180);
    const w = Math.max((ext.maxX - ext.minX) * k, 1e-6); const h = Math.max(ext.maxY - ext.minY, 1e-6);
    const s = Math.min((W * 0.9) / w, (H * 0.9) / h);
    const ox = (W - w * s) / 2; const oy = (H - h * s) / 2;
    return (p: number[]) => [ox + (p[0] - ext.minX) * k * s, H - (oy + (p[1] - ext.minY) * s)];
  }, [ext]);
  const [view, setView] = useState({ x: 0, y: 0, z: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  if (!ext || !proj) return <div className="mapbox" style={{ display: 'grid', placeItems: 'center', height }}><span className="muted">Nothing to draw here yet.</span></div>;
  const vw = W / view.z; const vh = H / view.z;
  const vx = view.x + (W - vw) / 2; const vy = view.y + (H - vh) / 2;
  const zoom = (f: number) => setView((v) => ({ ...v, z: Math.min(40, Math.max(1, v.z * f)) }));
  const path = (g: Geometry) => rings(g).map((r) => 'M' + r.map((p) => proj(p).map((n) => n.toFixed(1)).join(',')).join('L') + (g.type.includes('Polygon') ? 'Z' : '')).join(' ');
  const order = (f: Feature) => (f.properties.kind === 'layer' ? 0 : f.properties.kind === 'overlap' ? 1 : 2);
  const kinds = Array.from(new Set(feats.filter((f) => f.properties.kind === 'layer').map((f) => String(f.properties.layer_kind ?? 'other'))));
  const hasOverlap = feats.some((f) => f.properties.kind === 'overlap');
  const stroke = 1.5 / view.z;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div style={{ position: 'relative' }}>
        <svg ref={svgRef} className="mapbox" viewBox={`${vx} ${vy} ${vw} ${vh}`} role="img" aria-label="Map of plots and layers" style={height ? { height, aspectRatio: 'auto' } : undefined}
          onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; (e.target as Element).setPointerCapture?.(e.pointerId); }}
          onPointerMove={(e) => {
            if (!drag.current || !svgRef.current) return;
            const r = svgRef.current.getBoundingClientRect();
            const dx = ((e.clientX - drag.current.x) / r.width) * vw; const dy = ((e.clientY - drag.current.y) / r.height) * vh;
            drag.current = { x: e.clientX, y: e.clientY };
            setView((v) => ({ ...v, x: v.x - dx, y: v.y - dy }));
          }}
          onPointerUp={() => { drag.current = null; }}>
          <defs>
            <pattern id="p-dots" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#dcdcd4" /><circle cx="4" cy="4" r="1.4" fill="#3a3a3a" /></pattern>
            <pattern id="p-lines" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="#e2dfd7" /><line x1="0" y1="0" x2="0" y2="8" stroke="#0b0b0b" strokeWidth="1.2" /></pattern>
            <pattern id="p-cross" width="10" height="10" patternUnits="userSpaceOnUse"><rect width="10" height="10" fill="#e9e6df" /><path d="M0 0L10 10M10 0L0 10" stroke="#0b0b0b" strokeWidth="0.8" /></pattern>
            <pattern id="p-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#0b0b0b" strokeWidth="2" /></pattern>
          </defs>
          <rect x={-W * 40} y={-H * 40} width={W * 81} height={H * 81} fill="#e9e6df" />
          {[...feats].sort((a, b) => order(a) - order(b)).map((f, i) => {
            const p = f.properties;
            const sel = selected && (p.asset_id === selected || p.flag_id === selected);
            if (f.geometry.type === 'Point') {
              const [x, y] = proj(f.geometry.coordinates as number[]);
              return <circle key={i} cx={x} cy={y} r={8 / view.z} fill="#a3ee5b" stroke="#0b0b0b" strokeWidth={stroke * 1.5} onClick={() => onSelect?.(f)} style={{ cursor: onSelect ? 'pointer' : 'default' }}><title>{String(p.reference ?? '')}</title></circle>;
            }
            if (p.kind === 'layer') {
              const st = LAYER_STYLE[String(p.layer_kind ?? 'other')] ?? LAYER_STYLE.other;
              return <path key={i} d={path(f.geometry)} fill={st.fill} fillOpacity={0.85} stroke={st.stroke} strokeWidth={stroke} strokeDasharray={st.dash} fillRule="evenodd"><title>{`${st.label}: ${String(p.name || p.layer_name || '')}${p.is_sample ? ' (sample)' : ''}`}</title></path>;
            }
            if (p.kind === 'overlap') {
              return <path key={i} d={path(f.geometry)} fill="url(#p-hatch)" fillOpacity={0.6} stroke="#0b0b0b" strokeWidth={stroke * 2} strokeDasharray="6 3" onClick={() => onSelect?.(f)} style={{ cursor: 'pointer' }}><title>{`Overlapping plot ${String(p.other_reference ?? '')}`}</title></path>;
            }
            return <path key={i} d={path(f.geometry)} fill={p.disputed ? 'url(#p-cross)' : '#a3ee5b'} fillOpacity={0.75} stroke="#0b0b0b" strokeWidth={stroke * (sel ? 4 : 2)} onClick={() => onSelect?.(f)} style={{ cursor: onSelect ? 'pointer' : 'default' }}><title>{`${String(p.reference ?? 'Plot')}${p.locality ? ` · ${String(p.locality)}` : ''}${p.disputed ? ' · disputed' : ''}`}</title></path>;
          })}
        </svg>
        <div style={{ position: 'absolute', right: 8, top: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <button type="button" className="btn btn-dark" style={{ width: 44, padding: 0 }} onClick={() => zoom(1.5)} aria-label="Zoom in">+</button>
          <button type="button" className="btn btn-dark" style={{ width: 44, padding: 0 }} onClick={() => zoom(1 / 1.5)} aria-label="Zoom out">−</button>
          <button type="button" className="btn btn-dark" style={{ width: 44, padding: 0, fontSize: 12 }} onClick={() => setView({ x: 0, y: 0, z: 1 })} aria-label="Fit">Fit</button>
        </div>
      </div>
      <div className="legend" aria-label="Legend">
        <span><i style={{ background: '#a3ee5b', border: '1.5px solid #0b0b0b' }} />Plot</span>
        {feats.some((f) => f.properties.disputed) ? <span><i style={{ background: 'repeating-linear-gradient(45deg,#0b0b0b 0 1px,#e9e6df 1px 5px)', border: '1.5px solid #0b0b0b' }} />Disputed plot</span> : null}
        {hasOverlap ? <span><i style={{ background: 'repeating-linear-gradient(-45deg,#0b0b0b 0 2px,transparent 2px 6px)', border: '1.5px dashed #0b0b0b' }} />Overlapping plot</span> : null}
        {kinds.map((k) => { const st = LAYER_STYLE[k] ?? LAYER_STYLE.other; return <span key={k}><i style={{ background: st.fill.startsWith('url') ? '#cfccc4' : st.fill, border: `1.5px ${st.dash ? 'dashed' : 'solid'} ${st.stroke}` }} />{st.label}</span>; })}
      </div>
    </div>
  );
}
