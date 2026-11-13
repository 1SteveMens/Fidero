'use client';
/* Approvals queue: every open approval this person could give, oldest first. Each opens its detail, which
 * links to the dedicated screen where its extra checks run. */
import Link from 'next/link';
import { useState } from 'react';
import { Empty, Field, ProblemBox, Select, Skeleton, useGet } from '@tenmina/web-ui';
import { dayTime, Head } from '@/components/core/kit';
import { dedicatedHref, SUBJECT_LABEL } from '@/components/core/approvalLinks';
import type { Approval, Page } from '@/components/core/types';

export default function Approvals() {
  const [status, setStatus] = useState('open');
  const [type, setType] = useState('');
  const list = useGet<Page<Approval>>('/v1/approvals', { status, ...(type ? { subject_type: type } : {}) });
  const items = list.data?.items ?? [];
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head title="Approvals" sub="Two people approve every release. The person who prepared something never approves it." />
      <div className="filters">
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Open</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="withdrawn">Withdrawn</option>
          </Select>
        </Field>
        <Field label="Kind">
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All kinds</option>
            {Object.entries(SUBJECT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={5} /> : items.length ? (
        <div className="rows">
          {items.map((a) => (
            <Link key={a.id} href={`/approvals/${a.id}`} className="rowlink">
              <div className="main">
                <div className="label">{SUBJECT_LABEL[a.subject_type] ?? a.subject_type}{dedicatedHref(a.subject_type, a.subject_id) ? ' · own screen' : ''}</div>
                <div className="title">{a.summary || a.subject_id}</div>
                <div className="meta">Asked {dayTime(a.created_at)}{a.approvals.length ? ` · ${a.approvals.map((x) => x.approver_name).join(', ')}` : ''}</div>
              </div>
              <span className="chip">{a.approvals.filter((x) => x.decision === 'approve').length} of {a.required}</span>
            </Link>
          ))}
        </div>
      ) : <Empty>{status === 'open' ? 'No approvals are waiting for you.' : 'None in this list.'}</Empty>}
    </div>
  );
}
