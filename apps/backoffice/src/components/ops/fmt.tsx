'use client';
/* Render API values the Bloc way: references and dates in mono, money with its
 * currency, statuses as neutral chips, verdicts with icon and word. */
import React from 'react';
import { Chip, Money, Status, Verdict, When } from '@tenmina/web-ui';
import type { Col, Row } from './spec';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_DT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const ISO_D = /^\d{4}-\d{2}-\d{2}$/;

const WORDS: Record<string, string> = {
  id: 'ID', url: 'URL', sha256: 'SHA-256', mfa: 'MFA', aml: 'AML', boq: 'Bill of quantities', qs: 'Quantity surveyor',
  pdf: 'PDF', api: 'API', otp: 'Code', fx: 'Exchange', dpo: 'Data protection officer', ip: 'IP',
};

export function humanize(key: string): string {
  const parts = key.replace(/\./g, ' ').split(/[_\s]+/).filter(Boolean);
  const s = parts.map((p) => WORDS[p.toLowerCase()] ?? p.toLowerCase()).join(' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function get(row: Row | null | undefined, path: string): unknown {
  if (!row) return undefined;
  return path.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Row)[k] : undefined), row);
}

export function isMoney(v: unknown): v is { amount: string; currency: string } {
  return !!v && typeof v === 'object' && 'amount' in (v as Row) && 'currency' in (v as Row) && Object.keys(v as Row).length <= 3;
}

/** A one-line name for an object: reference, name, label or a short id. */
export function nameOf(v: unknown): string {
  if (v == null) return '—';
  if (typeof v !== 'object') return String(v);
  const r = v as Row;
  for (const k of ['reference', 'name', 'full_name', 'legal_name', 'display_name', 'title', 'label', 'email', 'code', 'key']) {
    if (r[k]) return String(r[k]);
  }
  return r.id ? shortId(String(r.id)) : JSON.stringify(r).slice(0, 60);
}

export function shortId(id: string) {
  return UUID.test(id) ? id.slice(0, 8) + '…' + id.slice(-4) : id;
}

export function titleOf(r: Row | undefined): string {
  if (!r) return '';
  for (const k of ['reference', 'name', 'legal_name', 'full_name', 'title', 'label', 'email', 'description', 'kind']) {
    if (r[k] && typeof r[k] === 'string') return r[k];
  }
  return r.id ? shortId(String(r.id)) : '';
}

/** Automatic rendering for a value under a key. */
export function Value({ k, v }: { k: string; v: unknown }): React.ReactElement {
  if (v === null || v === undefined || v === '') return <span className="muted">—</span>;
  if (typeof v === 'boolean') return <span>{v ? 'Yes' : 'No'}</span>;
  if (typeof v === 'number') return <span className="mono">{v.toLocaleString('en-GB')}</span>;
  if (isMoney(v)) return <Money value={v} />;
  if (typeof v === 'string') {
    if (k === 'verdict' || k.endsWith('_verdict')) return <Verdict value={v} />;
    if (k === 'status' || k.endsWith('_status') || k === 'state') return <Status value={v} />;
    if (ISO_DT.test(v)) return <When value={v} withTime />;
    if (ISO_D.test(v)) return <When value={v} />;
    if (UUID.test(v)) return <span className="mono" title={v}>{shortId(v)}</span>;
    if (k === 'reference' || k.endsWith('_reference') || k.endsWith('sha256') || k.endsWith('_hash') || k === 'hash' || k.endsWith('_number') || k === 'code') {
      return <span className="mono" style={{ overflowWrap: 'anywhere' }}>{v}</span>;
    }
    return <span style={{ whiteSpace: 'pre-wrap' }}>{v}</span>;
  }
  if (Array.isArray(v)) {
    if (!v.length) return <span className="muted">None</span>;
    if (v.every((x) => typeof x !== 'object' || x === null)) return <span>{v.map((x) => String(x).replace(/_/g, ' ')).join(', ')}</span>;
    if (isChecklist(v as Row[])) return <Checklist items={v as Row[]} />;
    return <MiniTable rows={v as Row[]} />;
  }
  if (typeof v === 'object') {
    const r = v as Row;
    const keys = Object.keys(r);
    if (keys.length <= 4 && (r.name || r.full_name || r.reference || r.legal_name)) {
      return (
        <span>
          {nameOf(r)}
          {r.status ? <> <Status value={r.status} /></> : null}
        </span>
      );
    }
    return <Nested obj={r} />;
  }
  return <span>{String(v)}</span>;
}

const DONE_KEYS = ['done', 'ok', 'passed', 'met', 'checked'];
function isChecklist(rows: Row[]) {
  return rows.every((r) => r && typeof r === 'object' && ('label' in r || 'message' in r || 'rule' in r) && DONE_KEYS.some((k) => k in r));
}

/** Gates and checklists: lime tick when met, an empty box when not. */
export function Checklist({ items }: { items: Row[] }) {
  return (
    <ul className="ops-checklist">
      {items.map((r, i) => {
        const ok = DONE_KEYS.some((k) => r[k] === true);
        return (
          <li key={i} className={ok ? 'ok' : ''}>
            <span className="tick" aria-hidden>{ok ? '✓' : ''}</span>
            <span>
              <span style={{ fontWeight: 600 }}>{String(r.label ?? r.message ?? r.rule)}</span>
              <span className="sr-only">{ok ? ' (done)' : ' (not yet)'}</span>
              {r.detail ? <small className="muted" style={{ display: 'block' }}>{String(r.detail)}</small> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Nested({ obj }: { obj: Row }) {
  const entries = Object.entries(obj).filter(([, x]) => x !== null && x !== '' && x !== undefined);
  if (!entries.length) return <span className="muted">—</span>;
  return (
    <dl className="kv ops-nested">
      {entries.map(([k, x]) => (
        <React.Fragment key={k}>
          <dt>{humanize(k)}</dt>
          <dd><Value k={k} v={x} /></dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

/** Columns for an array of objects: up to six simple fields. */
export function autoColumns(rows: Row[], max = 6): Col[] {
  const keys: string[] = [];
  for (const r of rows.slice(0, 5)) {
    for (const [k, v] of Object.entries(r)) {
      if (keys.includes(k) || k === 'id') continue;
      if (v !== null && typeof v === 'object' && !isMoney(v) && !(v as Row).name && !(v as Row).reference && !(v as Row).full_name) continue;
      keys.push(k);
    }
  }
  const order = (k: string) => (k === 'reference' ? 0 : k.includes('name') || k === 'label' || k === 'title' ? 1 : k === 'status' ? 3 : 2);
  return keys.sort((a, b) => order(a) - order(b)).slice(0, max).map((k) => ({ key: k, label: humanize(k) }));
}

export function Cell({ col, row }: { col: Col; row: Row }) {
  if (col.render) return <>{col.render(row)}</>;
  const v = get(row, col.key);
  switch (col.kind) {
    case 'ref':
    case 'mono':
      return v ? <span className="mono" style={{ overflowWrap: 'anywhere' }}>{typeof v === 'object' ? nameOf(v) : String(v)}</span> : <span className="muted">—</span>;
    case 'status':
      return <Status value={v as string} />;
    case 'verdict':
      return <Verdict value={v as string} />;
    case 'money':
      return <Money value={v as never} />;
    case 'date':
      return <When value={v as string} />;
    case 'when':
      return <When value={v as string} withTime />;
    case 'bool':
      return v ? <Chip tone="lime">✓ Yes</Chip> : <span className="muted">No</span>;
    case 'count':
      return <span className="mono">{Array.isArray(v) ? v.length : String(v ?? 0)}</span>;
    case 'name':
      return <span style={{ fontWeight: 700 }}>{nameOf(v)}</span>;
    case 'text':
      return <span>{v == null || v === '' ? '—' : String(v)}</span>;
    default:
      return <Value k={col.key.split('.').pop() || col.key} v={v} />;
  }
}

export function MiniTable({ rows, columns }: { rows: Row[]; columns?: Col[] }) {
  const cols = columns ?? autoColumns(rows);
  return (
    <div className="table-wrap">
      <table className="table responsive ops-mini">
        <thead><tr>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${(r.id as string) ?? ''}-${i}`}>
              {cols.map((c) => <td key={c.key} data-label={c.label}><Cell col={c} row={r} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
