'use client';
/* Cases: every case in this person's countries, newest first, with filters. */
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { Button, Empty, Field, Input, ProblemBox, Select, Skeleton, useClient, call } from '@tenmina/web-ui';
import useSWRInfinite from 'swr/infinite';
import { day, Head, words } from '@/components/core/kit';
import type { Case, Page } from '@/components/core/types';

const STATUSES = ['paid', 'in_progress', 'on_hold', 'in_review', 'released', 'completed', 'cancelled'];
const LINES = ['land', 'building', 'fresh_search', 'institution_verification', 'property_onboarding', 'vendor_verification', 'supplier_check', 'contractor_check', 'developer_check', 'offplan_check'];

export default function Cases() {
  const client = useClient();
  const [status, setStatus] = useState('');
  const [line, setLine] = useState('');
  const [q, setQ] = useState('');
  const query = { ...(status ? { status } : {}), ...(line ? { product_line: line } : {}) };
  const pages = useSWRInfinite<Page<Case>>(
    (i, prev) => (i > 0 && !prev?.next_cursor ? null : ['/v1/cases', JSON.stringify(query), i > 0 ? prev?.next_cursor : null]),
    ([, , cursor]) => call<Page<Case>>(client, 'GET', '/v1/cases', undefined, { ...query, ...(cursor ? { cursor } : {}) }),
  );
  const all = useMemo(() => (pages.data ?? []).flatMap((p) => p.items), [pages.data]);
  const needle = q.trim().toLowerCase();
  const rows = all.filter((c) => !needle || `${c.reference} ${c.title} ${c.client?.name ?? ''}`.toLowerCase().includes(needle));
  const more = pages.data?.[pages.data.length - 1]?.next_cursor;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head title="Cases" sub="Every case follows its template. Open a case to see its tasks, requests, parties, searches and costs." />
      <div className="filters">
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All open and closed</option>
            {STATUSES.map((s) => <option key={s} value={s}>{words(s)}</option>)}
          </Select>
        </Field>
        <Field label="Line">
          <Select value={line} onChange={(e) => setLine(e.target.value)}>
            <option value="">All lines</option>
            {LINES.map((s) => <option key={s} value={s}>{words(s)}</option>)}
          </Select>
        </Field>
        <Field label="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Reference, title or client" /></Field>
      </div>
      <ProblemBox error={pages.error} />
      {pages.isLoading ? <Skeleton lines={6} /> : rows.length ? (
        <div className="rows">
          {rows.map((c) => (
            <Link key={c.id} href={`/cases/${c.id}`} className="rowlink">
              <div className="main">
                <div className="mono" style={{ fontSize: 12 }}>{c.reference} · {words(c.product_line)}</div>
                <div className="title">{c.title}</div>
                <div className="meta">{c.client?.name ?? 'No client'}{c.case_manager ? ` · ${c.case_manager.name}` : ''} · opened {day(c.created_at)}</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                {c.risk_flag ? <span className="chip chip-ink">Risk flag</span> : null}
                <span className="chip">{words(c.status)}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : <Empty>No cases match. New cases appear here when an order is paid.</Empty>}
      {more ? <Button variant="ghost" onClick={() => pages.setSize(pages.size + 1)} busy={pages.isValidating}>Show more</Button> : null}
    </div>
  );
}
