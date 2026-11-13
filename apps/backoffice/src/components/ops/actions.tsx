'use client';
/* One button per workflow step. Fields come from the API schema; the step-up
 * code is asked for first where the action needs it, or when the API says so. */
import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError } from '@tenmina/api-client';
import { Button, call, CodeBoxes, Dialog, Field, HoldButton, Input, ProblemBox, Select, Textarea, useSession } from '@tenmina/web-ui';
import formsJson from './forms.json';
import { humanize, Value } from './fmt';
import type { ActionSpec, FieldSpec, Opt, Row } from './spec';

type SchemaField = { n: string; t?: string; e?: string[]; f?: string; i?: string; r?: number; d?: string };
const FORMS = formsJson as unknown as Record<string, SchemaField[] | { q: string[]; s?: string[] }>;
const norm = (k: string) => k.replace(/\{[^}]+\}/g, '{}');
const NORMED: Record<string, SchemaField[] | { q: string[]; s?: string[] }> = {};
for (const [k, v] of Object.entries(FORMS)) NORMED[norm(k)] = v;

export function schemaFor(method: string, path: string): SchemaField[] {
  const v = NORMED[norm(`${method} ${path}`)];
  return Array.isArray(v) ? v : [];
}
export function listInfo(path: string): { q: string[]; s?: string[] } {
  const v = NORMED[norm(`GET ${path}`)];
  return v && !Array.isArray(v) ? v : { q: [] };
}

/** Fill a path template: {id} is the row, {parent} the parent row, other names read row then parent fields. */
export function fill(path: string, row: Row, parent?: Row): string {
  return path.replace(/\{([^}]+)\}/g, (_, name: string) => {
    if (name === 'id') return encodeURIComponent(String(row.id ?? ''));
    if (name === 'parent') return encodeURIComponent(String(parent?.id ?? ''));
    const v = row[name] ?? parent?.[name];
    return encodeURIComponent(String(v ?? ''));
  });
}

const LONG = new Set(['note', 'notes', 'reason', 'reasons', 'comment', 'description', 'summary', 'body', 'text', 'message', 'statement', 'outcome_note', 'action_taken', 'findings', 'explanation', 'detail', 'answer']);

function toFieldSpec(s: SchemaField): FieldSpec {
  const f: FieldSpec = { name: s.n, required: !!s.r, hint: s.d };
  if (s.e?.length) { f.type = 'select'; f.options = s.e.map((e) => ({ value: e, label: humanize(e) })); }
  else if (s.t === 'boolean') f.type = 'bool';
  else if (s.t === 'integer' || s.t === 'number' || s.f === 'decimal') f.type = 'number';
  else if (s.t === 'money') f.type = 'money';
  else if (s.t === 'object') f.type = 'json';
  else if (s.t === 'array') f.type = s.i === 'string' ? (/evidence|photo|document_ids/.test(s.n) ? 'files' : 'list') : 'json';
  else if (s.f === 'date') f.type = 'date';
  else if (s.f === 'date-time') f.type = 'datetime';
  else if (s.f === 'binary') f.type = 'binary';
  else if (s.f === 'uuid' && s.n.includes('evidence')) f.type = 'file';
  else if (LONG.has(s.n)) f.type = 'textarea';
  else f.type = 'text';
  return f;
}

export function fieldsFor(a: ActionSpec, row: Row, parent?: Row): FieldSpec[] {
  const method = a.method ?? 'POST';
  const fixed = typeof a.fixed === 'function' ? a.fixed(row, parent) : a.fixed ?? {};
  const raw = schemaFor(method, a.path);
  const hasEvidenceId = raw.some((s) => s.f === 'uuid' && s.n.includes('evidence'));
  let base = raw.filter((s) => !(s.f === 'binary' && hasEvidenceId)).map(toFieldSpec).filter((f) => !/_?base64$/.test(f.name));
  // Files go up as sealed evidence first; the raw-file alternatives are not shown.
  if (base.some((f) => f.type === 'file' || f.type === 'files')) base = base.filter((f) => !['content_type', 'file_name', 'filename'].includes(f.name));
  if (a.only) base = base.filter((f) => a.only!.includes(f.name));
  if (a.omit) base = base.filter((f) => !a.omit!.includes(f.name));
  const over = a.fields ?? [];
  const merged = base.map((f) => {
    const o = over.find((x) => x.name === f.name);
    return o ? { ...f, ...o } : f;
  });
  for (const o of over) if (!merged.some((f) => f.name === o.name)) merged.push({ type: 'text', ...o });
  return merged.filter((f) => !(f.name in fixed));
}

/* Toasts shared by every action on a screen, so they survive the button going away. */
const ToastCtx = createContext<(m: string) => void>(() => undefined);
export function OpsToasts({ children }: { children: React.ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = useCallback((m: string) => {
    setMsg(m);
    setTimeout(() => setMsg((x) => (x === m ? null : x)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg ? <div className="toast" role="status">{msg}</div> : null}
    </ToastCtx.Provider>
  );
}
export const useOpsToast = () => useContext(ToastCtx);

function readCookie(name: string) {
  return document.cookie.split('; ').find((c) => c.startsWith(name + '='))?.split('=')[1];
}

async function sha256Hex(buf: ArrayBuffer) {
  const h = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Upload one file as tamper-evident evidence; returns the evidence id. */
export async function uploadEvidence(client: Parameters<typeof call>[0], file: File, subject_type: string, subject_id: string, role = 'supporting', country?: string): Promise<Row> {
  const buf = await file.arrayBuffer();
  const sha256 = await sha256Hex(buf);
  const slot = await call<Row>(client, 'POST', '/v1/uploads', {
    subject_type, subject_id, role, content_type: file.type || 'application/octet-stream', size_bytes: file.size, sha256, original_name: file.name, ...(country ? { country } : {}),
  });
  const up = slot.upload as { url: string; method: string; headers: Record<string, string> };
  const res = await fetch(up.url, { method: up.method || 'PUT', credentials: 'include', headers: { ...up.headers, 'X-CSRFToken': readCookie('csrftoken') ?? '' }, body: buf });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError({ type: '', title: data.title ?? 'Upload failed', status: res.status, detail: data.detail ?? '', code: data.code ?? 'upload-failed', errors: data.errors, blocking_reasons: data.blocking_reasons });
  return data as Row;
}

/** For endpoints that take the file itself (multipart), e.g. a provider settlement file. */
async function sendMultipart(method: string, path: string, fields: FieldSpec[], values: Record<string, unknown>, body: Record<string, unknown>): Promise<Row> {
  const fd = new FormData();
  for (const [k, v] of Object.entries(body)) {
    if (v === undefined || v === null) continue;
    fd.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  }
  for (const f of fields) if (f.type === 'binary' && values[f.name] instanceof File) fd.append(f.name, values[f.name] as File);
  const res = await fetch(path, { method, body: fd, credentials: 'include', headers: { 'X-CSRFToken': readCookie('csrftoken') ?? '', 'Idempotency-Key': crypto.randomUUID() } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError({ type: '', title: data.title ?? res.statusText, status: res.status, detail: data.detail ?? '', code: data.code ?? 'error', errors: data.errors, blocking_reasons: data.blocking_reasons });
  return data as Row;
}

export async function download(path: string, fallbackName: string) {
  const res = await fetch(path, { credentials: 'include' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError({ type: '', title: data.title ?? 'Download failed', status: res.status, detail: data.detail ?? '', code: data.code ?? 'error' });
  }
  const cd = res.headers.get('content-disposition') ?? '';
  const name = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function initial(fields: FieldSpec[], row: Row, parent?: Row, home?: string | null): Record<string, unknown> {
  const v: Record<string, unknown> = {};
  for (const f of fields) {
    const d = typeof f.default === 'function' ? (f.default as (r: Row, p?: Row) => unknown)(row, parent) : f.default;
    if (d !== undefined) v[f.name] = d;
    else if (f.name === 'country' && home) v[f.name] = typeof row.country === 'string' && row.country.length === 2 ? row.country : home;
    else if (f.type === 'bool') v[f.name] = false;
    else if (f.type === 'money') v[f.name] = { amount: '', currency: row.currency ?? row.amount?.currency ?? parent?.currency ?? '' };
  }
  return v;
}

function buildBody(fields: FieldSpec[], values: Record<string, unknown>, fixed: Record<string, unknown>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (f.type === 'bool') { body[f.name] = !!v; continue; }
    if (f.type === 'binary') continue;
    if (v === undefined || v === null || v === '') continue;
    switch (f.type) {
      case 'number': body[f.name] = Number(v); break;
      case 'datetime': body[f.name] = new Date(String(v)).toISOString(); break;
      case 'json':
        try { body[f.name] = typeof v === 'string' ? JSON.parse(v) : v; } catch { throw new Error(`${f.label ?? humanize(f.name)}: this is not valid JSON.`); }
        break;
      case 'list': body[f.name] = String(v).split(/\n|,/).map((x) => x.trim()).filter(Boolean); break;
      case 'money': {
        const m = v as { amount: string; currency: string };
        if (m.amount !== '') body[f.name] = { amount: String(m.amount), currency: m.currency.toUpperCase() };
        break;
      }
      default: body[f.name] = v;
    }
  }
  return { ...body, ...fixed };
}

function SourceSelect({ f, row, parent, value, onChange }: { f: FieldSpec; row: Row; parent?: Row; value: string; onChange: (v: string) => void }) {
  const { client } = useSession();
  const [opts, setOpts] = useState<Opt[] | null>(null);
  const src = f.source!;
  const path = fill(typeof src.path === 'function' ? src.path(row, parent) : src.path, row, parent);
  React.useEffect(() => {
    let live = true;
    call<Row>(client, 'GET', path, undefined, src.query).then((d) => {
      const items: Row[] = Array.isArray(d) ? d : (d.items as Row[]) ?? [];
      if (live) setOpts(items.map((r) => ({ value: String(r[src.value ?? 'id']), label: src.label(r) })));
    }).catch(() => live && setOpts([]));
    return () => { live = false; };
  }, [client, path]); // eslint-disable-line react-hooks/exhaustive-deps
  if (opts === null) return <Select disabled><option>Loading…</option></Select>;
  if (!opts.length) return <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder="Nothing to choose from: paste an ID" />;
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)} required={f.required}>
      <option value="">Choose…</option>
      {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </Select>
  );
}

function FileField({ f, subject, subjectId, country, value, onChange, multiple }: { f: FieldSpec; subject?: string; subjectId: string; country?: string; value: unknown; onChange: (v: unknown) => void; multiple?: boolean }) {
  const { client } = useSession();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [names, setNames] = useState<string[]>([]);
  const st = f.upload?.subject_type ?? subject;
  if (!st) return <Input value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} placeholder="Evidence ID" />;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <input
        type="file"
        multiple={multiple}
        className="input"
        aria-label={f.label ?? humanize(f.name)}
        onChange={async (e) => {
          const files = Array.from(e.target.files ?? []);
          if (!files.length) return;
          setBusy(true); setErr(null);
          try {
            const ids: string[] = [];
            for (const file of files) {
              const ev = await uploadEvidence(client, file, st, subjectId, f.upload?.role, country);
              ids.push(String(ev.id));
            }
            setNames(files.map((x) => x.name));
            onChange(multiple ? [...((value as string[]) ?? []), ...ids] : ids[0]);
          } catch (x) { setErr(x); } finally { setBusy(false); }
        }}
      />
      {busy ? <small className="muted">Uploading and sealing…</small> : null}
      {names.length && !busy ? <small><span className="chip chip-lime">✓ Sealed</span> {names.join(', ')}</small> : null}
      <ProblemBox error={err} />
    </div>
  );
}

export function FormFields({ fields, values, set, row, parent, subject }: {
  fields: FieldSpec[]; values: Record<string, unknown>; set: (k: string, v: unknown) => void; row: Row; parent?: Row; subject?: string;
}) {
  const { me } = useSession();
  return (
    <>
      {fields.filter((f) => f.type !== 'hidden').map((f) => {
        const label = (f.label ?? humanize(f.name)) + (f.required ? '' : ' (optional)');
        const val = values[f.name];
        const sv = val == null ? '' : String(val);
        let input: React.ReactNode;
        const opts = typeof f.options === 'function' ? f.options(row, parent) : f.options;
        if (f.source) input = <SourceSelect f={f} row={row} parent={parent} value={sv} onChange={(v) => set(f.name, v)} />;
        else if (opts) {
          input = (
            <Select value={sv} onChange={(e) => set(f.name, e.target.value)} required={f.required}>
              <option value="">Choose…</option>
              {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          );
        } else {
          switch (f.type) {
            case 'textarea': input = <Textarea rows={3} value={sv} onChange={(e) => set(f.name, e.target.value)} required={f.required} />; break;
            case 'json': input = <Textarea rows={4} className="textarea mono" value={typeof val === 'object' && val !== null ? JSON.stringify(val, null, 1) : sv} onChange={(e) => set(f.name, e.target.value)} placeholder="{ }" />; break;
            case 'list': input = <Textarea rows={3} value={Array.isArray(val) ? val.join('\n') : sv} onChange={(e) => set(f.name, e.target.value)} placeholder="One per line" />; break;
            case 'binary':
              input = <input type="file" className="input" aria-label={f.label ?? humanize(f.name)} onChange={(e) => set(f.name, e.target.files?.[0] ?? null)} />;
              break;
            case 'textfile':
              input = (
                <div className="stack" style={{ gap: 6 }}>
                  <input type="file" className="input" aria-label={f.label ?? humanize(f.name)} onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    set(f.name, await file.text());
                    if (f.fileNameField) set(f.fileNameField, file.name);
                  }} />
                  {sv ? <small className="muted">{sv.split('\n').length} lines read</small> : null}
                </div>
              );
              break;
            case 'number': input = <Input type="number" inputMode="decimal" step="any" value={sv} onChange={(e) => set(f.name, e.target.value)} required={f.required} />; break;
            case 'date': input = <Input type="date" value={sv} onChange={(e) => set(f.name, e.target.value)} required={f.required} />; break;
            case 'datetime': input = <Input type="datetime-local" value={sv} onChange={(e) => set(f.name, e.target.value)} required={f.required} />; break;
            case 'bool':
              return (
                <label key={f.name} className="row ops-check">
                  <input type="checkbox" checked={!!val} onChange={(e) => set(f.name, e.target.checked)} />
                  <span>{f.label ?? humanize(f.name)}{f.hint ? <small className="muted" style={{ display: 'block' }}>{f.hint}</small> : null}</span>
                </label>
              );
            case 'money': {
              const m = (val as { amount: string; currency: string }) ?? { amount: '', currency: '' };
              input = (
                <div className="row" style={{ flexWrap: 'nowrap' }}>
                  <Input aria-label="Currency" style={{ width: 90 }} maxLength={3} value={m.currency} onChange={(e) => set(f.name, { ...m, currency: e.target.value })} placeholder="CUR" />
                  <Input aria-label="Amount" type="number" step="0.01" inputMode="decimal" value={m.amount} onChange={(e) => set(f.name, { ...m, amount: e.target.value })} />
                </div>
              );
              break;
            }
            case 'file':
            case 'files': {
              const sid = f.upload?.subjectId ? f.upload.subjectId(row, parent) : String(row.id ?? parent?.id ?? '');
              const ctry = [values.country, row.country, parent?.country, me?.home_country].find((c) => typeof c === 'string' && c.length === 2) as string | undefined;
              input = <FileField f={f} subject={subject} subjectId={sid} country={ctry} value={val} onChange={(v) => set(f.name, v)} multiple={f.type === 'files'} />;
              break;
            }
            default: input = <Input value={sv} onChange={(e) => set(f.name, e.target.value)} required={f.required} />;
          }
        }
        return <Field key={f.name} label={label} hint={f.type === 'bool' ? undefined : f.hint}>{input}</Field>;
      })}
    </>
  );
}

/** A workflow button. Opens a form when the step needs input, a code or a hold. */
export function ActionButton({ a, row, parent, onDone, subject, size = 'sm' }: {
  a: ActionSpec; row: Row; parent?: Row; onDone?: (result: unknown) => void; subject?: string; size?: 'sm' | 'md';
}) {
  const { client, stepUp, hasRole, me } = useSession();
  const toast = useOpsToast();
  const router = useRouter();
  const fields = useMemo(() => fieldsFor(a, row, parent), [a, row, parent]);
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [code, setCode] = useState('');
  const [needCode, setNeedCode] = useState(!!a.mfa);
  const [result, setResult] = useState<Row | null>(null);

  if (a.roles && !hasRole(...a.roles)) return null;
  if (a.when && !a.when(row, parent)) return null;

  const visible = fields.filter((f) => f.type !== 'hidden');
  const confirmText = typeof a.confirm === 'function' ? a.confirm(row, parent) : a.confirm;
  const needsDialog = visible.length > 0 || !!confirmText || !!a.mfa || !!a.hold;

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      if (needCode) {
        if (code.length !== 6) throw new Error('Enter the six-digit code from your authenticator.');
        await stepUp(code);
      }
      const path = fill(a.path, row, parent);
      if (a.download) {
        await download(path, a.download);
        toast(a.done ?? 'Downloaded. The download is logged.');
        setOpen(false);
        return;
      }
      const fixed = typeof a.fixed === 'function' ? a.fixed(row, parent) : a.fixed ?? {};
      const body = buildBody(fields, values, fixed);
      const method = a.method ?? 'POST';
      const res = fields.some((f) => f.type === 'binary')
        ? await sendMultipart(method, path, fields, values, body)
        : await call<Row>(client, method as 'POST', path, method === 'DELETE' ? undefined : body);
      toast(a.done ?? `${a.label}: done.`);
      onDone?.(res);
      const to = a.goto?.(res ?? {}, row);
      if (to) { setOpen(false); router.push(to); return; }
      if (a.showResult && res) { setResult(res); setOpen(true); }
      else { setOpen(false); setValues({}); setCode(''); setNeedCode(!!a.mfa); }
    } catch (e) {
      if (e instanceof ApiError && e.problem.code === 'mfa-required') {
        setNeedCode(true); setOpen(true); setCode('');
        setErr(new Error('This step needs a fresh authenticator code. Enter it and try again.'));
      } else {
        setErr(e); setOpen(true);
      }
    } finally {
      setBusy(false);
    }
  };

  const tone = a.tone ?? 'dark';
  return (
    <>
      <Button
        size={size}
        variant={tone}
        busy={busy && !open}
        onClick={() => {
          if (needsDialog) { setValues(initial(fields, row, parent, me?.home_country)); setErr(null); setResult(null); setOpen(true); }
          else run();
        }}
      >
        {a.label}
      </Button>
      <Dialog open={open} onClose={() => { setOpen(false); setResult(null); }} title={a.label} ink={a.ink}>
        {result ? (
          <div className="stack">
            <p>Done. Copy anything you need now: it may not be shown again.</p>
            <dl className="kv">
              {Object.entries(result).filter(([, v]) => v !== null && v !== '').slice(0, 16).map(([k, v]) => (
                <React.Fragment key={k}><dt>{humanize(k)}</dt><dd><Value k={k} v={v} /></dd></React.Fragment>
              ))}
            </dl>
            <Button onClick={() => { setOpen(false); setResult(null); }}>Close</Button>
          </div>
        ) : (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); if (!a.hold) run(); }}>
            {confirmText ? <p style={{ margin: 0 }}>{confirmText}</p> : null}
            <FormFields fields={fields} values={values} set={(k, v) => setValues((s) => ({ ...s, [k]: v }))} row={row} parent={parent} subject={subject} />
            {needCode ? (
              <Field label="Code from your authenticator">
                <CodeBoxes value={code} onChange={setCode} autoFocus={!visible.length} />
              </Field>
            ) : null}
            <ProblemBox error={err} />
            {a.hold ? (
              <HoldButton tone="lime" label={busy ? 'Working…' : a.label} onConfirm={run} disabled={busy} />
            ) : (
              <Button type="submit" variant={tone === 'ghost' ? 'dark' : tone} busy={busy} block>{a.label}</Button>
            )}
          </form>
        )}
      </Dialog>
    </>
  );
}
