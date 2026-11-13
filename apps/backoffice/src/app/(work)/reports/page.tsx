'use client';
/* Reports: the list, the monthly re-check queue (SCR-BO-45, RUL-32) and re-check incidents. */
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Empty, Field, Input, ProblemBox, Select, Skeleton, Tabs, useGet, useSession, Verdict } from '@tenmina/web-ui';
import { ActionForm, day, Head, Panel, words } from '@/components/core/kit';
import type { Page, Report } from '@/components/core/types';

type Recheck = { id: string; subject_type: string; subject_id: string; case: string; case_reference: string; report: string | null; assignee: string | null; assignee_role: string; assigned_at: string | null; due_at: string | null; status: string; result: string; findings: string; result_at: string | null; incident: string | null; skip_reason: string };
type Month = { draw: { id: string; sample_month: string; sample_pct: string; population_count: number; selected_count: number; seed: string; population_sha256: string; drawn_at: string } | null; items: Recheck[]; summary: Record<string, unknown> };
type Cand = { id: string; name: string; role: string; licence_number: string; licence_expires_on: string };
type Incident = { id: string; case: string; recheck: string | null; report: string | null; kind: string; summary: string; correction_report: string | null; client_notified_at: string | null; status: string; closure_note: string; closed_at: string | null; created_at: string };

function ReportList() {
  const [status, setStatus] = useState('');
  const list = useGet<Page<Report>>('/v1/reports', { limit: 100, ...(status ? { status } : {}) });
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {['draft', 'in_review', 'approved', 'released', 'superseded'].map((s) => <option key={s} value={s}>{words(s)}</option>)}
          </Select>
        </Field>
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={5} /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((r) => (
            <Link key={r.id} href={`/reports/${r.id}`} className="rowlink">
              <div className="main"><div className="mono" style={{ fontSize: 12 }}>{r.reference} · v{r.version}</div><div className="title">Case {r.case_reference}</div><div className="meta">{r.released_at ? `Released ${day(r.released_at)}` : `Started ${day(r.created_at)}`}{r.release_error ? ' · release blocked' : ''}</div></div>
              <div className="row" style={{ gap: 6 }}><span className="chip">{words(r.status)}</span><Verdict value={r.overall_verdict} /></div>
            </Link>
          ))}
        </div>
      ) : <Empty>No reports yet. A report starts from its case.</Empty>}
    </div>
  );
}

function AssignRecheck({ r, onDone }: { r: Recheck; onDone: () => void }) {
  const cand = useGet<Cand[]>(`/v1/rechecks/${r.id}/candidates`);
  const opts = (cand.data ?? []).map((c) => ({ value: `${c.id}|${c.role}`, label: `${c.name} · ${c.role === 'LW' ? 'lawyer' : 'surveyor'} · licence ${c.licence_number}` }));
  return (
    <ActionForm label={r.assignee ? 'Reassign' : 'Assign'} variant="dark" path={`/v1/rechecks/${r.id}/assignments`} title="Assign the re-check"
      intro={cand.isLoading ? 'Loading eligible people…' : opts.length ? 'Only licensed people with no link to the case are listed (RUL-32).' : 'No eligible person: everyone licensed is linked to this case. Skip it with a reason.'}
      fields={[{ name: 'who', label: 'Professional', type: 'select', required: true, options: opts }]} body={(v) => { const [person_id, role] = String(v.who).split('|'); return { person_id, role }; }} onDone={onDone} submitLabel="Assign" />
  );
}

function Rechecks() {
  const { me, hasRole } = useSession();
  const now = new Date();
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`);
  const reviewer = hasRole('RV', 'AD');
  const m = useGet<Month>('/v1/rechecks', reviewer ? { month, country: 'GH' } : {});
  const items = m.data?.items ?? [];
  return (
    <div className="stack">
      {reviewer ? (
        <div className="filters">
          <Field label="Month"><Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
          {!m.data?.draw ? <ActionForm label="Run this month's draw" variant="dark" path="/v1/rechecks/draws" onDone={() => m.mutate()} body={() => ({ month: `${month}-01`, country: 'GH' })} submitLabel="Draw" intro="Normally the monthly job draws. One draw per month; a second is refused and logged." /> : null}
        </div>
      ) : <p className="muted" style={{ margin: 0 }}>Re-checks assigned to you. Do not contact the original team.</p>}
      <ProblemBox error={m.error} />
      {m.data?.draw ? (
        <Panel title={`Draw for ${day(m.data.draw.sample_month)}`}>
          <dl className="facts">
            <div><dt>Share</dt><dd>{m.data.draw.sample_pct}% [TO VERIFY]</dd></div>
            <div><dt>Population</dt><dd>{m.data.draw.population_count}</dd></div>
            <div><dt>Selected</dt><dd>{m.data.draw.selected_count}</dd></div>
            <div><dt>Drawn</dt><dd className="mono">{day(m.data.draw.drawn_at)}</dd></div>
            <div><dt>Seed</dt><dd className="mono" style={{ fontSize: 11 }}>{m.data.draw.seed.slice(0, 16)}…</dd></div>
          </dl>
        </Panel>
      ) : null}
      {m.isLoading ? <Skeleton lines={4} /> : items.length ? (
        <div className="rows">
          {items.map((r) => {
            const mine = r.assignee === me?.id && r.status === 'assigned';
            return (
              <div key={r.id} className={`rowlink ${mine ? 'late' : ''}`}>
                <div className="main">
                  <div className="mono" style={{ fontSize: 12 }}>{r.case_reference} · {words(r.subject_type)}</div>
                  <div className="title">{r.status === 'done' ? `${r.result === 'confirmed' ? '✓ Confirmed' : `✕ ${words(r.result)}`}` : r.status === 'skipped' ? `Skipped: ${r.skip_reason}` : r.assignee ? `Assigned (${r.assignee_role === 'LW' ? 'lawyer' : 'surveyor'})` : 'Not assigned yet'}</div>
                  <div className="meta">{r.due_at ? `Due ${day(r.due_at)}` : ''}{r.findings ? ` · ${r.findings}` : ''}{r.incident ? ' · incident opened, releases frozen' : ''}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {mine ? <span className="chip chip-orange">Yours</span> : <span className="chip">{words(r.status)}</span>}
                  {reviewer && ['selected', 'assigned'].includes(r.status) ? <AssignRecheck r={r} onDone={() => m.mutate()} /> : null}
                  {reviewer && ['selected', 'assigned'].includes(r.status) ? <ActionForm label="Skip" path={`/v1/rechecks/${r.id}/skips`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={() => m.mutate()} submitLabel="Skip" /> : null}
                  {r.status === 'assigned' && r.assignee === me?.id ? (
                    <ActionForm label="Record result" variant="primary" path={`/v1/rechecks/${r.id}/results`} fields={[
                      { name: 'result', label: 'Result', type: 'select', required: true, options: [{ value: 'confirmed', label: 'Confirmed' }, { value: 'correction_needed', label: 'Correction needed' }, { value: 'failed', label: 'Failed' }] },
                      { name: 'findings', label: 'What you found', type: 'textarea' },
                    ]} onDone={() => m.mutate()} submitLabel="Save result" intro="A failed re-check opens an incident, starts the client notice of any correction and freezes releases on affected escrows." />
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : <Empty>{reviewer ? (m.data?.draw ? (m.data.draw.selected_count ? 'No re-check you may see. Each is hidden from people linked to its case (RUL-32).' : 'Nothing was selected this month.') : 'No draw for this month yet.') : 'No re-checks assigned to you.'}</Empty>}
    </div>
  );
}

function Incidents() {
  const list = useGet<Page<Incident>>('/v1/report-incidents');
  return (
    <div className="stack">
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((i) => (
            <div key={i.id} className="rowlink">
              <div className="main">
                <div className="label">{words(i.kind)} · opened {day(i.created_at)}</div>
                <div className="title">{i.summary}</div>
                <div className="meta">{i.correction_report ? <Link href={`/reports/${i.correction_report}`}>Correction</Link> : 'No correction yet'}{i.client_notified_at ? ` · client told ${day(i.client_notified_at)}` : ''}{i.closure_note ? ` · ${i.closure_note}` : ''}</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                {i.status === 'open' ? <span className="strip-ink" style={{ padding: '4px 10px', fontSize: 13 }}>🔒 Releases frozen</span> : <span className="chip">{words(i.status)}</span>}
                {i.status === 'open' ? <ActionForm label="Close" path={`/v1/report-incidents/${i.id}/close`} fields={[{ name: 'note', label: 'What was done', type: 'textarea', required: true }]} onDone={() => list.mutate()} submitLabel="Close incident" intro="Close once any correction is released and the client has been told. The escrow freezes lift." /> : null}
              </div>
            </div>
          ))}
        </div>
      ) : <Empty>No re-check incidents.</Empty>}
    </div>
  );
}

function ReportsHome() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get('tab') ?? 'reports';
  const { hasRole } = useSession();
  const tabs = [{ key: 'reports', label: 'Reports' }, { key: 'rechecks', label: 'Re-checks' }, ...(hasRole('RV', 'AD') ? [{ key: 'incidents', label: 'Incidents' }] : [])];
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head title="Reports" sub="Built from the versioned template. Released reports never change; corrections are new versions." />
      <div className="tabs-scroll"><Tabs items={tabs} current={tab} onChange={(k) => router.replace(`/reports?tab=${k}`)} /></div>
      {tab === 'reports' ? <ReportList /> : tab === 'rechecks' ? <Rechecks /> : <Incidents />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton />}><ReportsHome /></Suspense>;
}
