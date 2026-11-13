'use client';
/* Small building blocks shared by the role pages (professionals, sellers, contractors, institutions,
   insurers, partners, family members, tenants and authorities). Bloc rules: lime for proof and the
   main action, orange only for this person's own step, black grounds for money. */
import Link from 'next/link';
import React, { useCallback, useState } from 'react';
import { Button, CodeBoxes, Dialog, Empty, Field, ProblemBox, Skeleton, useClient, useSession, useToast, call } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { openEvidence } from './files';

export type Page<T> = { items: T[]; next_cursor?: string | null };
export type { MoneyT };

/** Lists from the API come as {items} pages or as plain arrays. */
export function items<T>(d: Page<T> | T[] | undefined | null): T[] {
  if (!d) return [];
  return Array.isArray(d) ? d : d.items ?? [];
}

export function words(s?: string | null): string {
  if (!s) return '—';
  const t = s.replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function PageHead({ label, title, children, back }: { label?: string; title: string; children?: React.ReactNode; back?: { href: string; label: string } }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      {back ? <Link href={back.href} className="muted" style={{ textDecoration: 'none', fontWeight: 700, minHeight: 32 }}>← {back.label}</Link> : null}
      {label ? <p className="label" style={{ margin: 0 }}>{label}</p> : null}
      <h1 style={{ marginBottom: 4 }}>{title}</h1>
      {children ? <div className="muted">{children}</div> : null}
    </div>
  );
}

/** A tappable row that links to a detail page. */
export function RowLink({ href, title, meta, right, sub }: { href: string; title: React.ReactNode; meta?: React.ReactNode; right?: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <Link href={href} className="card card-link rl-row">
      <div style={{ minWidth: 0, flex: 1 }}>
        {meta ? <div className="label">{meta}</div> : null}
        <div style={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{title}</div>
        {sub ? <div className="muted" style={{ fontSize: 14 }}>{sub}</div> : null}
      </div>
      {right ? <div className="rl-right">{right}</div> : null}
    </Link>
  );
}

export function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="stack" style={{ marginTop: 8 }}>
      <div className="spread"><h2 style={{ margin: 0 }}>{title}</h2>{action}</div>
      {children}
    </section>
  );
}

/** Loading, error and empty states around a list or a record. */
export function Loaded<T>({ q, children }: { q: { data?: T; error?: unknown; isLoading: boolean }; children: (d: T) => React.ReactNode }) {
  if (q.isLoading) return <Skeleton lines={4} />;
  if (q.error) return <ProblemBox error={q.error} />;
  if (q.data === undefined) return <Skeleton lines={2} />;
  return <>{children(q.data)}</>;
}

export function EmptyText({ children }: { children: React.ReactNode }) {
  return <Empty>{children}</Empty>;
}

/** Run an API action with a busy flag, a problem box and a toast. */
export function useAct() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(key);
    setError(null);
    try {
      const r = await fn();
      if (ok) toast.show(ok);
      return r;
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [toast]);
  return { run, busy, error, setError, toast: toast.node, show: toast.show };
}

/** The API's typed client for JSON calls. */
export function useApi() {
  const client = useClient();
  return useCallback(<T = unknown,>(method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body?: unknown, query?: Record<string, unknown>) => call<T>(client, method, path, body, query), [client]);
}

/** Ask for a fresh second-factor code, then run the action (signing, money and other irreversible steps). */
export function StepUpDialog({ open, onClose, title, onConfirmed, children, ink }: { open: boolean; onClose: () => void; title: string; onConfirmed: () => Promise<void>; children?: React.ReactNode; ink?: boolean }) {
  const { stepUp, me } = useSession();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await stepUp(code);
      await onConfirmed();
      setCode('');
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onClose={onClose} title={title} ink={ink}>
      <form onSubmit={go} className="stack">
        {children}
        {me && !me.mfa_enabled ? <p>Set up an authenticator app first. Your Tenmina contact can help.</p> : null}
        <Field label="Code from your authenticator app"><CodeBoxes value={code} onChange={setCode} autoFocus /></Field>
        <ProblemBox error={error} />
        <Button variant="primary" type="submit" busy={busy} disabled={code.length !== 6} block>Confirm</Button>
      </form>
    </Dialog>
  );
}

export function EvidenceLink({ id, label = 'Open file' }: { id?: string | null; label?: string }) {
  const [err, setErr] = useState<unknown>(null);
  if (!id) return null;
  return (
    <>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => openEvidence(id).catch(setErr)}>{label}</button>
      {err ? <ProblemBox error={err} /> : null}
    </>
  );
}

/** A file input styled as a large target, with the chosen file's name. */
export function FilePick({ label, file, onFile, accept, hint }: { label: string; file: File | null; onFile: (f: File | null) => void; accept?: string; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <span className="filepick">
        <input type="file" accept={accept} onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        <span>{file ? file.name : 'Choose a file or take a photo'}</span>
      </span>
    </Field>
  );
}

/** "Paid to …, account ending …" (RUL-22, CMP-30). */
export function PayeeLine({ name, last4, bank, planned }: { name?: string | null; last4?: string | null; bank?: string | null; planned?: boolean }) {
  if (!name) return null;
  return (
    <span>{planned ? 'Will be paid to' : 'Paid to'} <strong>{name}</strong>{last4 ? <>, account ending <span className="mono">{last4}</span></> : null}{bank ? <span className="muted"> at {bank}</span> : null}</span>
  );
}

export function NotAllowed({ home }: { home?: string }) {
  return (
    <div className="stack">
      <h1>This page is not for your account</h1>
      <p className="muted">You can only see the work Tenmina has given you.</p>
      {home ? <Link className="btn btn-primary" href={home}>Go to your page</Link> : null}
    </div>
  );
}
