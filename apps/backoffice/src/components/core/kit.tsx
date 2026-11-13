'use client';
/* Shared pieces for the property and money core of the back office (cases, reports, maps, escrow, payees).
 * Bloc rules (03, 6.1d): lime for proof and the main action, orange only for this person's step,
 * black blocks for "Release blocked" and money approvals, neutral chips for status. */
import Link from 'next/link';
import React, { useState } from 'react';
import { ApiError } from '@tenmina/api-client';
import {
  Button, call, CodeBoxes, Dialog, Field, HoldButton, Input, ProblemBox, Select, Textarea, useSession, useToast,
} from '@tenmina/web-ui';
import { uploadEvidence } from './upload';
import './core.css';

/** snake_case to "Snake case". */
export function words(s?: string | null): string {
  if (!s) return '—';
  const t = s.replace(/[_-]+/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function short(id?: string | null): string {
  return id ? id.slice(-6).toUpperCase() : '—';
}

export function day(v?: string | null): string {
  if (!v) return '—';
  return new Date(v.length === 10 ? v + 'T12:00:00Z' : v).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function dayTime(v?: string | null): string {
  if (!v) return '—';
  return new Date(v).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function money(amount?: string | number | null, currency?: string | null): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const n = Number(amount);
  try {
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency: currency || 'GHS' }).format(n);
  } catch {
    return `${currency ?? ''} ${n.toFixed(2)}`;
  }
}

/** A titled block of the working area. */
export function Panel({ title, actions, children, id, ink }: { title: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; id?: string; ink?: boolean }) {
  return (
    <section className={`${ink ? 'card-ink' : 'card'} stack`} id={id} aria-label={typeof title === 'string' ? title : undefined}>
      <div className="spread">
        <h2 style={{ margin: 0, fontSize: 18 }}>{title}</h2>
        {actions ? <div className="row">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** Page header: crumb, title, chips and actions. */
export function Head({ crumb, title, chips, actions, sub }: { crumb?: { href: string; label: string }; title: React.ReactNode; chips?: React.ReactNode; actions?: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <header className="stack" style={{ gap: 8 }}>
      {crumb ? <Link href={crumb.href} className="label" style={{ textDecoration: 'none' }}>← {crumb.label}</Link> : null}
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <div className="stack" style={{ gap: 6, minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: 'clamp(24px, 5vw, 34px)', overflowWrap: 'anywhere' }}>{title}</h1>
          {chips ? <div className="row" style={{ gap: 6 }}>{chips}</div> : null}
          {sub ? <div className="muted" style={{ fontSize: 14 }}>{sub}</div> : null}
        </div>
        {actions ? <div className="row">{actions}</div> : null}
      </div>
    </header>
  );
}

/** A gate in a money approval: lime tick when it passes, a cross and the reason when it does not. */
export function Gate({ ok, title, detail, rule }: { ok: boolean; title: string; detail?: React.ReactNode; rule?: string }) {
  return (
    <div className="gate" data-ok={ok}>
      <span className="gate-mark" aria-hidden>{ok ? '✓' : '✕'}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700 }}>{title}{rule ? <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>{rule}</span> : null}</div>
        {detail ? <div style={{ fontSize: 14, opacity: 0.85 }}>{detail}</div> : null}
      </div>
      <span className="sr-only">{ok ? 'Passed' : 'Not passed'}</span>
    </div>
  );
}

export type Clock = { state?: string; working_days_running?: number | null; clock_started_at?: string | null; send_due_on?: string | null; bank_pay_due_on?: string | null; staff_approval_due_on?: string | null; frozen_reason?: string };

/** Release clock chip (FR-ESC-018, 5.6d): black on surface; orange only when overdue. */
export function ClockChip({ clock }: { clock?: Clock | null }) {
  if (!clock || !clock.clock_started_at) return <span className="chip">No clock yet</span>;
  const s = clock.state ?? 'running';
  const overdue = s === 'send_overdue' || s === 'bank_overdue';
  const text = s === 'paid' ? `Paid · day ${clock.working_days_running ?? 0}`
    : s === 'frozen' ? 'Clock frozen'
      : s === 'paused_shortfall' ? 'Waiting for top-up'
        : s === 'send_overdue' ? `Overdue: not sent · day ${clock.working_days_running ?? 0}`
          : s === 'bank_overdue' ? `Overdue: bank not paid · day ${clock.working_days_running ?? 0}`
            : `Day ${clock.working_days_running ?? 0}`;
  return <span className={`chip ${overdue ? 'chip-orange' : 'chip-clock'}`} title="Release clock">⏱ {text}</span>;
}

/** Run an API action with busy state, a problem box and a toast. */
export function useAct() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function run<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      const out = await fn();
      if (ok) toast.show(ok);
      return out;
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { run, busy, error, setError, toast: toast.node, show: toast.show };
}

export type FieldSpec = {
  name: string;
  label: string;
  type?: 'text' | 'textarea' | 'select' | 'date' | 'datetime' | 'number' | 'file' | 'checkbox' | 'money';
  options?: { value: string; label: string }[];
  required?: boolean;
  hint?: string;
  initial?: string | boolean;
  placeholder?: string;
};

export type Upload = { subject_type: string; subject_id: string; role?: string; country?: string };

/**
 * A button that opens a small form and sends it. File fields upload to the evidence store first and the
 * form gets the evidence id. `body(values)` builds the request; `method` defaults to POST.
 */
export function ActionForm({
  label, title, fields = [], path, method = 'POST', body, onDone, variant = 'ghost', size = 'sm', upload, intro,
  submitLabel, disabled, stepUp,
}: {
  label: string; title?: string; fields?: FieldSpec[]; path: string; method?: 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: (v: Record<string, string | boolean>) => unknown; onDone?: (out: unknown) => void;
  variant?: 'primary' | 'dark' | 'action' | 'ghost' | 'danger'; size?: 'sm' | 'md'; upload?: Upload; intro?: React.ReactNode;
  submitLabel?: string; disabled?: boolean; stepUp?: boolean;
}) {
  const { client, stepUp: doStepUp } = useSession();
  const [open, setOpen] = useState(false);
  const [vals, setVals] = useState<Record<string, string | boolean>>({});
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [code, setCode] = useState('');
  const act = useAct();
  const init = () => {
    const v: Record<string, string | boolean> = {};
    for (const f of fields) v[f.name] = f.initial ?? (f.type === 'checkbox' ? false : '');
    setVals(v);
    setFiles({});
    setCode('');
    act.setError(null);
  };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const out = await act.run(async () => {
      const v = { ...vals };
      for (const f of fields) {
        if (f.type === 'file') {
          const file = files[f.name];
          if (file) {
            if (!upload) throw new Error('No place to store this file.');
            v[f.name] = await uploadEvidence(client, file, { ...upload, role: upload.role ?? f.name.replace(/_id$/, '') });
          } else v[f.name] = '';
        }
      }
      if (stepUp) {
        if (code.length !== 6) throw new Error('Enter the six-digit code from your authenticator app.');
        await doStepUp(code);
      }
      return call(client, method, path, body ? body(v) : v);
    });
    if (out !== undefined) {
      setOpen(false);
      onDone?.(out);
    }
  }
  return (
    <>
      <Button variant={variant} size={size} onClick={() => { init(); setOpen(true); }} disabled={disabled}>{label}</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title={title ?? label}>
        <form className="stack" onSubmit={submit}>
          {intro ? <div className="muted" style={{ fontSize: 14 }}>{intro}</div> : null}
          {fields.map((f) => (
            <FormField key={f.name} spec={f} value={vals[f.name]} onChange={(x) => setVals((s) => ({ ...s, [f.name]: x }))} onFile={(file) => setFiles((s) => ({ ...s, [f.name]: file }))} />
          ))}
          {stepUp ? <Field label="Code from your authenticator app"><CodeBoxes value={code} onChange={setCode} /></Field> : null}
          <ProblemBox error={act.error} />
          <div className="row">
            <Button type="submit" variant="dark" busy={act.busy}>{submitLabel ?? 'Save'}</Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

function FormField({ spec, value, onChange, onFile }: { spec: FieldSpec; value: string | boolean | undefined; onChange: (v: string | boolean) => void; onFile: (f: File | null) => void }) {
  const t = spec.type ?? 'text';
  if (t === 'checkbox') {
    return (
      <label className="row" style={{ gap: 10, minHeight: 44, flexWrap: 'nowrap' }}>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} style={{ width: 22, height: 22 }} required={spec.required} />
        <span>{spec.label}</span>
      </label>
    );
  }
  let input: React.ReactNode;
  const v = typeof value === 'string' ? value : '';
  if (t === 'textarea') input = <Textarea value={v} onChange={(e) => onChange(e.target.value)} required={spec.required} placeholder={spec.placeholder} />;
  else if (t === 'select') {
    input = (
      <Select value={v} onChange={(e) => onChange(e.target.value)} required={spec.required}>
        <option value="">Choose…</option>
        {(spec.options ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </Select>
    );
  } else if (t === 'file') {
    input = <input className="input" type="file" accept="image/*,application/pdf,text/plain,text/csv,video/mp4" onChange={(e) => onFile(e.target.files?.[0] ?? null)} required={spec.required} />;
  } else {
    const it = t === 'datetime' ? 'datetime-local' : t === 'money' ? 'number' : t;
    input = <Input type={it} step={t === 'money' ? '0.01' : t === 'number' ? 'any' : undefined} inputMode={t === 'money' || t === 'number' ? 'decimal' : undefined} value={v} onChange={(e) => onChange(e.target.value)} required={spec.required} placeholder={spec.placeholder} />;
  }
  return <Field label={spec.label} hint={spec.hint}>{input}</Field>;
}

/** datetime-local value to ISO, or undefined. */
export function iso(v: string | boolean | undefined): string | undefined {
  if (!v || typeof v !== 'string') return undefined;
  return new Date(v).toISOString();
}

export function str(v: string | boolean | undefined): string | undefined {
  return typeof v === 'string' && v.trim() ? v.trim() : undefined;
}

/**
 * The person's own approval slot on a money or report approval (6.1d): outlined in orange, a confirmation box,
 * six code boxes, then press and hold. Steps up MFA and calls `onApprove`.
 */
export function MySlot({ title, confirmText, holdLabel, onApprove, disabled, disabledReason, onReturn, returnLabel = 'Return with comment' }: {
  title: string; confirmText?: string; holdLabel: string; onApprove: () => Promise<unknown>; disabled?: boolean; disabledReason?: string;
  onReturn?: (note: string) => Promise<unknown>; returnLabel?: string;
}) {
  const { stepUp } = useSession();
  const [code, setCode] = useState('');
  const [checked, setChecked] = useState(!confirmText);
  const [note, setNote] = useState('');
  const [showReturn, setShowReturn] = useState(false);
  const act = useAct();
  const ready = !disabled && checked && code.length === 6;
  async function approve() {
    await act.run(async () => { await stepUp(code); await onApprove(); });
    setCode('');
  }
  return (
    <div className="slot slot-mine stack">
      <div className="label" style={{ color: 'inherit' }}>{title} · You</div>
      {disabled ? <div style={{ fontWeight: 700 }}>{disabledReason}</div> : null}
      {confirmText ? (
        <label className="row" style={{ gap: 10, minHeight: 44, flexWrap: 'nowrap' }}>
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} style={{ width: 22, height: 22 }} disabled={disabled} />
          <span>{confirmText}</span>
        </label>
      ) : null}
      <Field label="Code from your authenticator app"><CodeBoxes value={code} onChange={setCode} /></Field>
      <ProblemBox error={act.error} />
      <HoldButton label={act.busy ? 'Working…' : holdLabel} tone="orange" onConfirm={approve} disabled={!ready || act.busy} />
      {onReturn ? (
        showReturn ? (
          <form className="stack" onSubmit={async (e) => { e.preventDefault(); await act.run(async () => { await stepUp(code); await onReturn(note); }); }}>
            <Field label="Comment" hint="Needs your code above as well."><Textarea value={note} onChange={(e) => setNote(e.target.value)} required /></Field>
            <Button type="submit" variant="ghost" size="sm" busy={act.busy} disabled={code.length !== 6}>{returnLabel}</Button>
          </form>
        ) : <button type="button" className="linkish" onClick={() => setShowReturn(true)}>{returnLabel}</button>
      ) : null}
      {act.toast}
    </div>
  );
}

/** A finished approval slot: name, time, code verified. */
export function DoneSlot({ title, name, at, decision }: { title: string; name: string; at?: string | null; decision?: string }) {
  const rejected = decision === 'reject' || decision === 'return';
  return (
    <div className="slot stack" style={{ gap: 4 }}>
      <div className="label" style={{ color: 'inherit' }}>{title}</div>
      <div className="row" style={{ gap: 8 }}>
        <span className={rejected ? 'gate-mark gate-no' : 'gate-mark'} aria-hidden>{rejected ? '✕' : '✓'}</span>
        <strong>{name}</strong>
      </div>
      <div className="mono" style={{ fontSize: 12, opacity: 0.8 }}>{dayTime(at)} · {rejected ? 'returned' : 'code verified'}</div>
    </div>
  );
}

export function OpenSlot({ title, text }: { title: string; text: string }) {
  return (
    <div className="slot stack" style={{ gap: 4, opacity: 0.75 }}>
      <div className="label" style={{ color: 'inherit' }}>{title}</div>
      <div>{text}</div>
    </div>
  );
}

/** Problem text for inline display (e.g. a 403 means the person's role does not allow it). */
export function problemText(e: unknown): string {
  if (e instanceof ApiError) return e.problem.detail || e.problem.title;
  return e ? String((e as Error).message ?? e) : '';
}

/** A list of label/value pairs as small mono rows that wrap on a phone. */
export function Facts({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="facts">
      {items.filter(([, v]) => v !== undefined).map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v === null || v === '' ? '—' : v}</dd></div>
      ))}
    </dl>
  );
}
