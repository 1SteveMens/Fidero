'use client';
import { useRef } from 'react';
import { Button } from '@tenmina/web-ui';

export type LngLat = { lng: number; lat: number };
const SPAN_M = 200; // the drawing area is 200 m across
const M_PER_DEG = 111320;

/**
 * Draw the plot's corners on a grid around a known point (W-04). A sketch for the
 * surveyor: the report uses the surveyor's own coordinates, never this drawing.
 */
export function PlotDrawer({ centre, points, onChange }: { centre: LngLat; points: LngLat[]; onChange: (p: LngLat[]) => void }) {
  const svg = useRef<SVGSVGElement>(null);
  const cos = Math.cos((centre.lat * Math.PI) / 180) || 1;
  const toXY = (p: LngLat) => ({ x: 150 + ((p.lng - centre.lng) * M_PER_DEG * cos * 300) / SPAN_M, y: 150 - ((p.lat - centre.lat) * M_PER_DEG * 300) / SPAN_M });
  const toLL = (x: number, y: number): LngLat => ({
    lng: +(centre.lng + (((x - 150) * SPAN_M) / 300) / (M_PER_DEG * cos)).toFixed(7),
    lat: +(centre.lat - (((y - 150) * SPAN_M) / 300) / M_PER_DEG).toFixed(7),
  });
  const xy = points.map(toXY);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <svg ref={svg} viewBox="0 0 300 300" className="map-box" role="application" aria-label="Plot drawing area. Tap each corner of the plot in order."
        onClick={(e) => {
          const r = svg.current!.getBoundingClientRect();
          onChange([...points, toLL(((e.clientX - r.left) / r.width) * 300, ((e.clientY - r.top) / r.height) * 300)]);
        }}>
        {Array.from({ length: 11 }).map((_, i) => (
          <g key={i} stroke="var(--color-line-strong)" strokeWidth="0.6">
            <line x1={i * 30} y1="0" x2={i * 30} y2="300" />
            <line x1="0" y1={i * 30} x2="300" y2={i * 30} />
          </g>
        ))}
        <circle cx="150" cy="150" r="4" fill="var(--color-text)" />
        <text x="156" y="146" fontSize="9" fill="var(--color-text-muted)">Your point</text>
        <text x="282" y="16" fontSize="12" fontWeight="800" fill="var(--color-text)">N</text>
        <line x1="10" y1="288" x2="55" y2="288" stroke="var(--color-text)" strokeWidth="2" />
        <text x="10" y="282" fontSize="9" fill="var(--color-text)">30 m</text>
        {xy.length > 2 ? <polygon points={xy.map((p) => `${p.x},${p.y}`).join(' ')} fill="rgba(163,238,91,.35)" stroke="#0b0b0b" strokeWidth="2" /> : null}
        {xy.length === 2 ? <line x1={xy[0].x} y1={xy[0].y} x2={xy[1].x} y2={xy[1].y} stroke="#0b0b0b" strokeWidth="2" /> : null}
        {xy.map((p, i) => <g key={i}><circle cx={p.x} cy={p.y} r="6" fill="#a3ee5b" stroke="#0b0b0b" strokeWidth="2" /><text x={p.x + 8} y={p.y - 6} fontSize="10" fontWeight="700" fill="var(--color-text)">{i + 1}</text></g>)}
      </svg>
      <div className="row">
        <Button type="button" variant="ghost" size="sm" disabled={!points.length} onClick={() => onChange(points.slice(0, -1))}>Undo last corner</Button>
        <Button type="button" variant="ghost" size="sm" disabled={!points.length} onClick={() => onChange([])}>Clear</Button>
        <span className="muted" style={{ fontSize: 13 }}>{points.length} corner{points.length === 1 ? '' : 's'}{points.length && points.length < 3 ? ', at least 3 needed' : ''}</span>
      </div>
    </div>
  );
}
