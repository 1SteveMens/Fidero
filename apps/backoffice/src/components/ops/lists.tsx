'use client';
/* Lists: filters from the API schema, cursor paging, one black action per row. */
import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button, call, Empty, Input, ProblemBox, Select, Skeleton, useGet, useSession, type Page } from '@tenmina/web-ui';
import { ActionButton, fill, listInfo } from './actions';
import { autoColumns, Cell, get, humanize } from './fmt';
import type { ActionSpec, Col, ResourceSpec, Row, SectionSpec } from './spec';

export function rowsOf(d: unknown): Row[] {
  if (!d) return [];
  if (Array.isArray(d)) return d as Row[];
  const o = d as Row;
  if (Array.isArray(o.items)) return o.items as Row[];
  for (const k of ['results', 'lines', 'data', 'entries', 'events']) if (Array.isArray(o[k])) return o[k] as Row[];
  // A single record (e.g. a review or a dashboard) shows as one row.
  return Object.keys(o).length ? [o] : [];
}

export function DataTable({ rows, columns, href, actions, parent, onDone, subject }: {
  rows: Row[]; columns: Col[]; href?: (r: Row) => string | undefined; actions?: ActionSpec[]; parent?: Row; onDone?: () => void; subject?: string;
}) {
  const router = useRouter();
  const cols = columns.length ? columns : autoColumns(rows);
  return (
    <div className="table-wrap">
      <table className="table responsive ops-table">
        <thead>
          <tr>
            {cols.map((c) => <th key={c.key}>{c.label}</th>)}
            {actions?.length ? <th aria-label="Actions" /> : null}
            {href ? <th aria-label="Open" /> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const to = href?.(r);
            return (
              <tr key={`${(r.id as string) ?? ''}-${i}`} className={to ? 'clickable' : ''} onClick={to ? () => router.push(to) : undefined}>
                {cols.map((c) => <td key={c.key} data-label={c.label}><Cell col={c} row={r} /></td>)}
                {actions?.length ? (
                  <td data-label="" onClick={(e) => e.stopPropagation()}>
                    <div className="row ops-row-actions">
                      {actions.map((a) => <ActionButton key={a.label} a={a} row={r} parent={parent} onDone={onDone} subject={subject} />)}
                    </div>
                  </td>
                ) : null}
                {to ? <td data-label="" className="ops-open"><Link href={to} onClick={(e) => e.stopPropagation()} className="btn btn-sm btn-dark">Open</Link></td> : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const TEXT_FILTERS = ['search', 'q', 'reference', 'email'];

export function ResourceList({ section, res }: { section: SectionSpec; res: ResourceSpec }) {
  const info = listInfo(res.list);
  const offered = (res.filters ?? ['status', ...TEXT_FILTERS]).filter((q) => info.q.includes(q) || (q === 'status' && info.s));
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [typed, setTyped] = useState<Record<string, string>>({});
  const { me } = useSession();
  const query: Record<string, unknown> = { ...(typeof res.listQuery === 'function' ? res.listQuery(me) : res.listQuery ?? {}) };
  for (const [k, v] of Object.entries(filters)) if (v) query[k] = v;
  const { data, error, isLoading, mutate } = useGet<Page<Row> | Row[]>(res.list, query);
  const { client } = useSession();
  const [more, setMore] = useState<Row[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreErr, setMoreErr] = useState<unknown>(null);

  useEffect(() => {
    setMore([]);
    setCursor(data && !Array.isArray(data) ? (data as Page<Row>).next_cursor : null);
  }, [data]);

  let rows = [...rowsOf(data), ...more];
  if (res.idKey) {
    const seen = new Set<string>();
    rows = rows.filter((r) => { const k = String(get(r, res.idKey!) ?? ''); if (!k || seen.has(k)) return false; seen.add(k); return true; });
  }
  const detail = res.detail === null ? null : res.detail ?? `${res.list}/{id}`;
  const href = detail ? (r: Row) => `${section.href}/${res.key}/${encodeURIComponent(String(get(r, res.idKey ?? 'id')))}` : undefined;

  return (
    <div className="stack">
      {res.intro ? <p className="muted" style={{ margin: 0 }}>{res.intro}</p> : null}
      <div className="row ops-toolbar">
        {offered.map((q) => (q === 'status' || q === 'check_status') && info.s ? (
          <label key={q} className="ops-filter">
            <span className="label">{humanize(q)}</span>
            <Select value={filters[q] ?? ''} onChange={(e) => setFilters((f) => ({ ...f, [q]: e.target.value }))}>
              <option value="">All</option>
              {info.s.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          </label>
        ) : (
          <form key={q} className="ops-filter" onSubmit={(e) => { e.preventDefault(); setFilters((f) => ({ ...f, [q]: typed[q] ?? '' })); }}>
            <span className="label">{q === 'q' || q === 'search' ? 'Search' : humanize(q)}</span>
            <Input type="search" value={typed[q] ?? ''} onChange={(e) => setTyped((t) => ({ ...t, [q]: e.target.value }))} placeholder={q === 'q' || q === 'search' ? 'Name, reference…' : ''} />
          </form>
        ))}
        {res.create ? <div className="ops-create"><ActionButton a={{ tone: 'primary', ...res.create }} row={{}} onDone={() => mutate()} size="md" subject={res.subject} /></div> : null}
      </div>
      {error ? <ProblemBox error={error} /> : isLoading ? <Skeleton lines={5} /> : rows.length ? (
        <DataTable rows={rows} columns={res.columns} href={href} actions={res.rowActions} onDone={() => mutate()} subject={res.subject} />
      ) : <Empty>Nothing here{Object.values(filters).some(Boolean) ? ' for these filters' : ' yet'}.</Empty>}
      {cursor ? (
        <Button variant="ghost" busy={loadingMore} onClick={async () => {
          setLoadingMore(true); setMoreErr(null);
          try {
            const d = await call<Page<Row>>(client, 'GET', res.list, undefined, { ...query, cursor });
            setMore((m) => [...m, ...d.items]);
            setCursor(d.next_cursor);
          } catch (e) { setMoreErr(e); } finally { setLoadingMore(false); }
        }}>Load more</Button>
      ) : null}
      <ProblemBox error={moreErr} />
    </div>
  );
}

/** A related list on a detail screen. */
export function SubList({ section, sub, parent, onParentChange, subject }: { section: SectionSpec; sub: SubSpecLike; parent: Row; onParentChange: () => void; subject?: string }) {
  const path = sub.path ? fill(sub.path, parent, parent) : null;
  const q = typeof sub.query === 'function' ? sub.query(parent) : sub.query;
  const { data, error, isLoading, mutate } = useGet<Page<Row> | Row[]>(path, q);
  const rows = sub.from ? ((parent[sub.from] as Row[]) ?? []) : rowsOf(data);
  const link = sub.link;
  const href = link ? (r: Row) => {
    const to = typeof link === 'function' ? link(r) : `${section.href}/${link}/${r.id}`;
    return to;
  } : undefined;
  const done = () => { mutate(); onParentChange(); };
  return (
    <section className="stack">
      <div className="spread">
        <h2 style={{ margin: 0 }}>{sub.label}</h2>
        {sub.create ? <ActionButton a={{ tone: 'dark', ...sub.create }} row={parent} onDone={done} subject={subject} /> : null}
      </div>
      {sub.note ? <p className="muted" style={{ margin: 0 }}>{sub.note}</p> : null}
      {error ? <ProblemBox error={error} /> : isLoading && !sub.from ? <Skeleton /> : rows.length ? (
        <DataTable rows={rows} columns={sub.columns ?? []} href={href} actions={sub.actions} parent={parent} onDone={done} subject={subject} />
      ) : <Empty>None yet.</Empty>}
    </section>
  );
}
type SubSpecLike = import('./spec').SubSpec;
