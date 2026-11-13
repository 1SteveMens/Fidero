'use client';
/* Bloc components for the portal and the back office (document 03, 6.1a to 6.1d). */
import React, { useEffect, useRef, useState } from 'react';
import { ApiError, formatMoney, type Money as MoneyT, type Problem } from '@tenmina/api-client';

type Btn = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'dark' | 'action' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  block?: boolean;
  busy?: boolean;
};

export function Button({ variant = 'dark', size = 'md', block, busy, className = '', children, disabled, ...rest }: Btn) {
  return (
    <button
      className={`btn btn-${variant} ${size === 'sm' ? 'btn-sm' : ''} ${block ? 'btn-block' : ''} ${className}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? 'Working…' : children}
    </button>
  );
}

export function Card({ ink, className = '', children, ...rest }: React.HTMLAttributes<HTMLDivElement> & { ink?: boolean }) {
  return (
    <div className={`${ink ? 'card-ink' : 'card'} ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function Chip({ tone, children }: { tone?: 'lime' | 'orange' | 'ink'; children: React.ReactNode }) {
  return <span className={`chip ${tone ? `chip-${tone}` : ''}`}>{children}</span>;
}

/** Verdict chip: always icon, word and colour (03, 6.1a). */
export function Verdict({ value }: { value?: string | null }) {
  const v = (value ?? '').toLowerCase();
  if (!v) return <Chip>No verdict yet</Chip>;
  const icon = v === 'green' ? '✓' : v === 'amber' ? '!' : v === 'red' ? '✕' : '?';
  const word = v.charAt(0).toUpperCase() + v.slice(1);
  return (
    <span className={`verdict verdict-${v}`} role="img" aria-label={`Verdict ${word}`}>
      <span aria-hidden>{icon}</span> {word}
    </span>
  );
}

/** Status as a neutral chip. Pass `needsYou` to mark it orange (only for the person who must act). */
export function Status({ value, needsYou }: { value?: string | null; needsYou?: boolean }) {
  const label = (value ?? '').replace(/_/g, ' ');
  return <Chip tone={needsYou ? 'orange' : undefined}>{label || '—'}</Chip>;
}

export function Money({ value, className = '' }: { value?: MoneyT | null; className?: string }) {
  return <span className={`money ${className}`} style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 800 }}>{formatMoney(value)}</span>;
}

export function Ref({ children }: { children: React.ReactNode }) {
  return <span className="mono">{children}</span>;
}

export function When({ value, withTime }: { value?: string | null; withTime?: boolean }) {
  if (!value) return <span className="mono muted">—</span>;
  const d = new Date(value);
  const s = withTime
    ? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  return <time className="mono" dateTime={value}>{s}</time>;
}

export function NeedsYou({ title, detail, href, onClick }: { title: string; detail?: string; href?: string; onClick?: () => void }) {
  const inner = (
    <>
      <div>
        <div className="label" style={{ color: '#0b0b0b' }}>Needs you</div>
        <div style={{ fontWeight: 800, fontSize: 17 }}>{title}</div>
        {detail ? <div style={{ fontSize: 14 }}>{detail}</div> : null}
      </div>
      <span className="arrow" aria-hidden>→</span>
    </>
  );
  return href ? (
    <a className="needs-you pulse" href={href}>{inner}</a>
  ) : (
    <button className="needs-you pulse" style={{ border: 0, width: '100%', textAlign: 'left', cursor: 'pointer' }} onClick={onClick}>
      {inner}
    </button>
  );
}

export function Blocked({ children, title = 'Release blocked' }: { children?: React.ReactNode; title?: string }) {
  return (
    <div className="banner-blocked" role="status">
      <span aria-hidden>🔒</span>
      <div>
        <strong>{title}</strong>
        {children ? <div style={{ fontSize: 14, opacity: 0.9 }}>{children}</div> : null}
      </div>
    </div>
  );
}

export function Field({ label, error, children, hint }: { label: string; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint ? <small className="muted">{hint}</small> : null}
      {error ? <small className="field-error">{error}</small> : null}
    </label>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(p, ref) {
  return <input ref={ref} className="input" {...p} />;
});
export function Select(p: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="select" {...p} />;
}
export function Textarea(p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="textarea" {...p} />;
}

export type Column<T> = { key: string; label: string; render: (row: T) => React.ReactNode; width?: string };

export function Table<T extends { id?: string }>({ rows, columns, onRowClick, empty }: {
  rows: T[]; columns: Column<T>[]; onRowClick?: (row: T) => void; empty?: React.ReactNode;
}) {
  if (!rows.length) return <Empty>{empty ?? 'Nothing here yet.'}</Empty>;
  return (
    <div className="table-wrap">
      <table className="table responsive">
        <thead>
          <tr>{columns.map((c) => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id ?? i} className={onRowClick ? 'clickable' : ''} onClick={onRowClick ? () => onRowClick(r) : undefined}>
              {columns.map((c) => <td key={c.key} data-label={c.label}>{c.render(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card muted" style={{ textAlign: 'center', padding: 28 }}>{children}</div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }).map((_, i) => <div key={i} className="skeleton" style={{ height: 22, width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

export function ProblemBox({ error }: { error: unknown }) {
  if (!error) return null;
  const p: Partial<Problem> = error instanceof ApiError ? error.problem : { title: String((error as Error)?.message ?? error) };
  return (
    <div className="error-box" role="alert">
      <strong>{p.title}</strong>
      {p.detail && p.detail !== p.title ? <div>{p.detail}</div> : null}
      {p.blocking_reasons?.length ? (
        <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          {p.blocking_reasons.map((b, i) => <li key={i}><span className="mono">{b.rule}</span> {b.message}</li>)}
        </ul>
      ) : null}
      {p.errors?.length ? (
        <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          {p.errors.map((e, i) => <li key={i}><span className="mono">{e.pointer.replace(/^\//, '')}</span>: {e.message}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

export function Steps({ items }: { items: { label: string; state: 'done' | 'now' | 'next'; detail?: string }[] }) {
  return (
    <div className="steps">
      {items.map((s, i) => (
        <div key={i} className={`step ${s.state}`}>
          <span className="dot" aria-hidden>{s.state === 'done' ? '✓' : ''}</span>
          <div>
            <div style={{ fontWeight: s.state === 'now' ? 800 : 600 }}>{s.label}{s.state === 'now' ? <span className="label" style={{ marginLeft: 8 }}>Now</span> : null}</div>
            {s.detail ? <div className="muted" style={{ fontSize: 14 }}>{s.detail}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Ticket: used only where money is about to move. Amount above the tear, who is paid below. */
export function Ticket({ top, bottom }: { top: React.ReactNode; bottom: React.ReactNode }) {
  return (
    <div className="ticket">
      <div className="ticket-top">{top}</div>
      <div className="ticket-tear" />
      <div className="ticket-bottom">{bottom}</div>
    </div>
  );
}

/** Six-box authenticator code field. */
export function CodeBoxes({ value, onChange, autoFocus }: { value: string; onChange: (v: string) => void; autoFocus?: boolean }) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.padEnd(6, ' ').slice(0, 6).split('');
  return (
    <div className="codeboxes" role="group" aria-label="Six-digit code">
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          aria-label={`Digit ${i + 1}`}
          autoFocus={autoFocus && i === 0}
          value={d.trim()}
          onChange={(e) => {
            const raw = e.target.value.replace(/\D/g, '');
            if (raw.length > 1) { onChange(raw.slice(0, 6)); refs.current[Math.min(5, raw.length - 1)]?.focus(); return; }
            const next = digits.map((x, j) => (j === i ? raw || ' ' : x)).join('').replace(/\s+$/, '');
            onChange(next.replace(/ /g, ''));
            if (raw && i < 5) refs.current[i + 1]?.focus();
          }}
          onKeyDown={(e) => { if (e.key === 'Backspace' && !d.trim() && i > 0) refs.current[i - 1]?.focus(); }}
        />
      ))}
    </div>
  );
}

/** Press and hold to confirm (03, 6.1a). Orange when it is the client's step, lime for staff proof steps. */
export function HoldButton({ label, onConfirm, tone = 'orange', ms = 1200, disabled }: {
  label: string; onConfirm: () => void; tone?: 'orange' | 'lime'; ms?: number; disabled?: boolean;
}) {
  const [holding, setHolding] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = () => {
    if (disabled) return;
    setHolding(true);
    timer.current = setTimeout(() => { setHolding(false); onConfirm(); }, ms);
  };
  const stop = () => { setHolding(false); if (timer.current) clearTimeout(timer.current); };
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return (
    <button
      type="button"
      className={`hold ${tone === 'lime' ? 'lime' : ''}`}
      disabled={disabled}
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) start(); }}
      onKeyUp={stop}
      aria-label={`${label}. Press and hold.`}
    >
      <span className="fill" style={{ width: holding ? '100%' : 0, transitionDuration: holding ? `${ms}ms` : '150ms' }} />
      <span>{holding ? 'Keep holding…' : label}</span>
    </button>
  );
}

export function Dialog({ open, onClose, title, children, ink }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; ink?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className={`dialog ${ink ? 'ground-ink' : ''}`} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function KV({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt>{k}</dt>
          <dd>{v ?? '—'}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export function Tabs({ items, current, onChange }: { items: { key: string; label: string }[]; current: string; onChange: (k: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button key={t.key} role="tab" aria-selected={t.key === current} className={`tab ${t.key === current ? 'active' : ''}`} onClick={() => onChange(t.key)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 3500);
    return () => clearTimeout(t);
  }, [msg]);
  const node = msg ? <div className="toast" role="status">{msg}</div> : null;
  return { show: setMsg, node };
}

export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#A3EE5B" />
      <path d="M9 10h14v3.2h-5.4V23h-3.2v-9.8H9z" fill="#0B0B0B" />
    </svg>
  );
}
