'use client';
/* Client portal building blocks on top of @tenmina/web-ui (03, 6.1a and 6.1b). */
import Link from 'next/link';
import React, { useCallback, useEffect, useState } from 'react';
import { ApiError, type Money as MoneyT } from '@tenmina/api-client';
import {
  Button, CodeBoxes, Dialog, HoldButton, Money, ProblemBox, Skeleton, Status, Ticket, call, useGet, useSession, useToast,
} from '@tenmina/web-ui';
import { toPortal } from '@/lib/links';
import './client.css';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Any = any;

/** Lists come back as `{items, next_cursor}` or as a plain array. */
export function list<T = Any>(d: unknown): T[] {
  if (!d) return [];
  if (Array.isArray(d)) return d as T[];
  const o = d as { items?: T[]; results?: T[] };
  return o.items ?? o.results ?? [];
}

export function words(s?: string | null): string {
  if (!s) return '';
  const t = s.replace(/[_-]+/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function money(amount?: string | number | null, currency?: string | null): MoneyT | null {
  if (amount === null || amount === undefined || amount === '' || !currency) return null;
  return { amount: String(amount), currency };
}

export function PageHead({ back, label, title, sub, right }: {
  back?: { href: string; label: string }; label?: string; title: React.ReactNode; sub?: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <header className="stack" style={{ gap: 6 }}>
      {back ? <Link href={back.href} className="pt-back">← {back.label}</Link> : null}
      {label ? <p className="label" style={{ margin: 0 }}>{label}</p> : null}
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <h1 style={{ margin: 0, minWidth: 0, overflowWrap: 'anywhere' }}>{title}</h1>
        {right}
      </div>
      {sub ? <div className="muted">{sub}</div> : null}
    </header>
  );
}

/** Black ground for approvals, the report, money and Account (6.1a). Bleeds to the page edges. */
export function Ink({ children }: { children: React.ReactNode }) {
  return <div className="ground-ink pt-ink"><div className="stack" style={{ gap: 16 }}>{children}</div></div>;
}

export function Section({ title, count, action, children }: { title: string; count?: number; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="stack" style={{ gap: 10 }}>
      <div className="spread">
        <h2 style={{ margin: 0 }}>{title}{count !== undefined ? <span className="muted" style={{ fontWeight: 600 }}> ({count})</span> : null}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** One thing at home: its name and one status sentence (CMP-06). */
export function Item({ href, title, sentence, meta, chip, amount, needs }: {
  href?: string; title: React.ReactNode; sentence?: React.ReactNode; meta?: React.ReactNode; chip?: React.ReactNode; amount?: MoneyT | null; needs?: boolean;
}) {
  const body = (
    <div className="spread" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
      <div style={{ minWidth: 0 }}>
        {meta ? <div className="label">{meta}</div> : null}
        <div style={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{title}</div>
        {sentence ? <div className={needs ? '' : 'muted'} style={{ fontSize: 14 }}>{needs ? <strong>! </strong> : null}{sentence}</div> : null}
      </div>
      <div className="stack" style={{ gap: 4, alignItems: 'flex-end', flex: 'none' }}>
        {chip}
        {amount ? <Money value={amount} /> : null}
      </div>
    </div>
  );
  const h = href && !/^\/(property|family|projects|account|inbox)(\/|$|\?)/.test(href) ? toPortal(href) : href;
  return h ? <Link href={h} className="card card-link">{body}</Link> : <div className="card">{body}</div>;
}

export function Loading({ q, children }: { q: { isLoading: boolean; error?: unknown }; children: React.ReactNode }) {
  if (q.isLoading) return <Skeleton lines={4} />;
  if (q.error) return <ProblemBox error={q.error} />;
  return <>{children}</>;
}

/** Run an API action: busy state, problem box and a toast; refresh data afterwards. */
export function useAction() {
  const { client } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, ok?: string, after?: (r: T) => void) => {
    setBusy(key);
    setError(null);
    try {
      const r = await fn();
      if (ok) toast.show(ok);
      after?.(r);
      return r;
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [toast]);
  const post = useCallback(<T = Any,>(path: string, body?: unknown, method: 'POST' | 'PUT' | 'PATCH' | 'DELETE' = 'POST') => call<T>(client, method, path, body), [client]);
  return { run, busy, error, setError, post, toast: toast.node, show: toast.show, client };
}

function readCookie(name: string) {
  return typeof document === 'undefined' ? undefined : document.cookie.split('; ').find((c) => c.startsWith(name + '='))?.split('=')[1];
}

async function sha256(buf: ArrayBuffer): Promise<string> {
  const h = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** FR-EVD-001: ask for an upload slot with the file's SHA-256, then send the bytes. Returns the evidence record. */
export async function uploadEvidence(client: Any, f: File, subject: { type: string; id: string; role?: string; country?: string; description?: string }): Promise<Any> {
  const buf = await f.arrayBuffer();
  const slot = await call<Any>(client, 'POST', '/v1/uploads', {
    subject_type: subject.type, subject_id: subject.id, role: subject.role ?? 'supporting', content_type: f.type || 'application/octet-stream',
    size_bytes: f.size, sha256: await sha256(buf), original_name: f.name, description: subject.description ?? '', country: subject.country,
  });
  const res = await fetch(`/v1/uploads/${slot.id}/content`, {
    method: 'PUT', body: buf, credentials: 'include',
    headers: { 'Content-Type': f.type || 'application/octet-stream', 'X-CSRFToken': readCookie('csrftoken') ?? '', 'Idempotency-Key': crypto.randomUUID() },
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError({ type: j.type ?? '', title: j.title ?? 'The upload failed', status: res.status, detail: j.detail ?? '', code: j.code ?? 'error', blocking_reasons: j.blocking_reasons, errors: j.errors });
  return j;
}

/** A file picker that stores the file as tamper-evident evidence, then hands back the evidence id. */
export function Upload({ subject, label = 'Upload a file', accept = 'image/*,application/pdf', onDone, variant = 'ghost' }: {
  subject: { type: string; id: string; role?: string; country?: string; description?: string };
  label?: string; accept?: string; onDone: (evidence: Any) => void | Promise<void>; variant?: 'ghost' | 'primary' | 'dark' | 'action';
}) {
  const { client } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [name, setName] = useState('');
  const id = React.useId();
  return (
    <div className="stack" style={{ gap: 6 }}>
      <label htmlFor={id} className={`btn btn-${variant}`} aria-busy={busy || undefined} style={{ cursor: 'pointer' }}>
        {busy ? 'Uploading…' : label}
      </label>
      <input id={id} type="file" accept={accept} className="sr-only" disabled={busy} onChange={async (e) => {
        const f = e.target.files?.[0];
        e.target.value = '';
        if (!f) return;
        setBusy(true); setError(null); setName(f.name);
        try { await onDone(await uploadEvidence(client, f, subject)); } catch (err) { setError(err); } finally { setBusy(false); }
      }} />
      {name && !busy && !error ? <small className="muted">Stored with its fingerprint: {name}</small> : null}
      <ProblemBox error={error} />
    </div>
  );
}

/**
 * The client's money approval (03, 5.4 and W-15): a ticket with the amount above the
 * tear and who is paid below it, then press and hold, then the authenticator code.
 * Silence is never approval: nothing happens until the client holds and enters the code.
 */
export function ApproveMoney({ amount, payee, payeeLines, above, holdLabel = 'Hold to approve', onApprove, onDecline, declineLabel = 'Decline', disabled, note }: {
  amount: MoneyT | null; payee: React.ReactNode; payeeLines?: React.ReactNode; above?: React.ReactNode; holdLabel?: string;
  onApprove: (code: string) => Promise<unknown>; onDecline?: (reason: string) => Promise<unknown>; declineLabel?: string; disabled?: boolean; note?: React.ReactNode;
}) {
  const { me } = useSession();
  const [ask, setAsk] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [decline, setDecline] = useState(false);
  const [reason, setReason] = useState('');
  async function go() {
    setBusy(true); setError(null);
    try { await onApprove(code); setAsk(false); setCode(''); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <div className="stack" style={{ gap: 14 }}>
      <Ticket
        top={<div className="stack" style={{ gap: 4 }}>{above}<div className="label" style={{ color: '#6a675f' }}>Amount</div><div style={{ fontSize: 34, fontWeight: 800 }}><Money value={amount} /></div></div>}
        bottom={<div className="stack" style={{ gap: 4 }}><div className="label" style={{ color: '#6a675f' }}>Paid to</div><div style={{ fontWeight: 800, fontSize: 18 }}>{payee}</div>{payeeLines}
          <div style={{ fontSize: 13, color: '#6a675f' }}>We never change who gets paid because of a message, email or call.</div></div>}
      />
      {note}
      {me && !me.mfa_enabled ? (
        <div className="card stack">
          <strong>Set up your authenticator app first.</strong>
          <span className="muted">Every money approval needs a code from your authenticator app.</span>
          <Link className="btn btn-primary" href="/account/security">Set up the app</Link>
        </div>
      ) : (
        <HoldButton label={holdLabel} disabled={disabled} onConfirm={() => { setError(null); setAsk(true); }} />
      )}
      {onDecline ? <Button variant="ghost" onClick={() => setDecline(true)}>{declineLabel}</Button> : null}
      {!ask ? <ProblemBox error={error} /> : null}
      <Dialog open={ask} onClose={() => setAsk(false)} title="Enter your code" ink>
        <div className="stack">
          <p className="muted">Open your authenticator app and enter the six-digit code for Tenmina.</p>
          <CodeBoxes value={code} onChange={setCode} autoFocus />
          <ProblemBox error={error} />
          <Button variant="action" busy={busy} disabled={code.length !== 6} onClick={go} block>Approve</Button>
        </div>
      </Dialog>
      <Dialog open={decline} onClose={() => setDecline(false)} title={declineLabel} ink>
        <div className="stack">
          <label className="field"><span>Why (optional)</span><textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <Button variant="dark" busy={busy} onClick={async () => {
            setBusy(true); setError(null);
            try { await onDecline?.(reason); setDecline(false); } catch (e) { setError(e); } finally { setBusy(false); }
          }} block>{declineLabel}</Button>
          <ProblemBox error={error} />
        </div>
      </Dialog>
    </div>
  );
}

export type AcctCardProps = { href?: string; title: string; reference?: string; amount: MoneyT | null; holder: string; bank?: string; note?: string };

/** Money held at the bank as account cards side by side (6.1a). Never a wallet, never a payment card. */
export function AcctRow({ children }: { children: React.ReactNode }) {
  return <div className="acct-row" role="list">{children}</div>;
}

export function AcctCard(c: AcctCardProps) {
  const inner = (
    <>
      <div className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div className="label" style={{ color: '#a9a69e' }}>{c.title}</div>
          {c.reference ? <div className="mono" style={{ fontSize: 13 }}>{c.reference}</div> : null}
        </div>
        <Seal />
      </div>
      <div style={{ fontSize: 24, fontWeight: 800, margin: '10px 0 2px', overflowWrap: 'anywhere' }}><Money value={c.amount} /></div>
      {c.note ? <div style={{ fontSize: 13, color: '#a9a69e' }}>{c.note}</div> : null}
      <div className="spread" style={{ fontSize: 13, marginTop: 'auto', paddingTop: 8 }}><span>{c.holder}</span><span style={{ color: '#a9a69e' }}>{c.bank}</span></div>
    </>
  );
  return c.href ? <Link role="listitem" href={c.href} className="acct-card">{inner}</Link> : <div role="listitem" className="acct-card">{inner}</div>;
}

export function Seal() {
  return (
    <svg className="seal" width="56" height="56" viewBox="0 0 100 100" aria-label="Held at the bank. Released on proof.">
      <defs><path id="sealc" d="M50,50 m-36,0 a36,36 0 1,1 72,0 a36,36 0 1,1 -72,0" /></defs>
      <circle cx="50" cy="50" r="48" fill="none" stroke="#a3ee5b" strokeWidth="2" />
      <text fontSize="10.5" fontFamily="IBM Plex Mono, monospace" fill="#a3ee5b" letterSpacing="1"><textPath href="#sealc">HELD AT THE BANK · RELEASED ON PROOF ·</textPath></text>
      <path d="M38 50l8 8 16-17" stroke="#a3ee5b" strokeWidth="6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Copy({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  useEffect(() => { if (!done) return; const t = setTimeout(() => setDone(false), 1500); return () => clearTimeout(t); }, [done]);
  return <button type="button" className="btn btn-ghost btn-sm" onClick={() => { navigator.clipboard?.writeText(value).then(() => setDone(true)).catch(() => undefined); }}>{done ? 'Copied' : 'Copy'}</button>;
}

/** Proof is lime: a tick and words. */
export function Proof({ children }: { children: React.ReactNode }) {
  return <span className="proof"><span aria-hidden>✓</span> {children}</span>;
}

export function StatusChip({ value, needs }: { value?: string | null; needs?: boolean }) {
  return <Status value={words(value)} needsYou={needs} />;
}

/** A small form inside a dialog for actions with a few fields. */
export function ActionDialog({ open, onClose, title, children, submit, busy, error, ink, onSubmit, disabled }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; submit: string; busy?: boolean; error?: unknown; ink?: boolean; onSubmit: () => void; disabled?: boolean;
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title} ink={ink}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
        {children}
        <ProblemBox error={error} />
        <Button variant="primary" type="submit" busy={busy} disabled={disabled} block>{submit}</Button>
      </form>
    </Dialog>
  );
}

export function Bar({ value, max, label }: { value: number; max: number; label?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="segbar" role="img" aria-label={label ?? `${pct} percent`}><span style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

/** The client's home country from configuration (DA-09): code, name and currency. Never hard-coded. */
export function useCountry(): { code: string; name: string; currency: string } {
  const { me } = useSession();
  const q = useGet<Any>('/v1/countries');
  const code = me?.home_country || 'GH';
  const c = list(q.data).find((x: Any) => x.code === code);
  return { code, name: c?.name ?? code, currency: c?.currency ?? '' };
}

/** Multipart POST (for endpoints that take a file directly). */
export async function postForm<T = Any>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: 'POST', body: form, credentials: 'include', headers: { 'X-CSRFToken': readCookie('csrftoken') ?? '', 'Idempotency-Key': crypto.randomUUID() } });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError({ type: j.type ?? '', title: j.title ?? 'That did not work', status: res.status, detail: j.detail ?? '', code: j.code ?? 'error', blocking_reasons: j.blocking_reasons, errors: j.errors });
  return j as T;
}

export function FilePick({ label, accept = 'image/*,application/pdf', onFile, busy }: { label: string; accept?: string; onFile: (f: File) => void; busy?: boolean }) {
  const id = React.useId();
  return (
    <>
      <label htmlFor={id} className="btn btn-ghost" style={{ cursor: 'pointer' }} aria-busy={busy || undefined}>{busy ? 'Uploading…' : label}</label>
      <input id={id} type="file" accept={accept} className="sr-only" disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onFile(f); }} />
    </>
  );
}

/** Choose one option as a large card (tiers, routes, choices). */
export function RadioCard({ name, checked, onChange, children }: { name: string; checked: boolean; onChange: () => void; children: React.ReactNode }) {
  return (
    <label className="radio-card" data-on={checked}>
      <input type="radio" name={name} checked={checked} onChange={onChange} />
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </label>
  );
}
