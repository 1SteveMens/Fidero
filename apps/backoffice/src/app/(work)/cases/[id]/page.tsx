'use client';
/* Case detail · SCR-BO-03 · W-12: template version, state, risk flag, tasks, what the client sees now, requests,
 * messages, parties and identity checks (SCR-BO-44), official searches (SCR-BO-43), costs, risk and safety. */
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Blocked, Button, call, ProblemBox, Skeleton, Tabs, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, Head, Panel, useAct, words } from '@/components/core/kit';
import { CaseTasks } from '@/components/core/case/CaseTasks';
import { CaseComms } from '@/components/core/case/CaseComms';
import { CaseParties } from '@/components/core/case/CaseParties';
import { CaseSearches } from '@/components/core/case/CaseSearches';
import { CaseCosts, CaseSafety } from '@/components/core/case/CaseMore';
import type { CaseDetail } from '@/components/core/types';

const TABS = [
  { key: 'tasks', label: 'Tasks' }, { key: 'client', label: 'Client and messages' }, { key: 'parties', label: 'Parties and ID' },
  { key: 'searches', label: 'Searches' }, { key: 'costs', label: 'Costs' }, { key: 'safety', label: 'Risk and safety' },
];
const VERIFY_LINES = ['institution_verification', 'vendor_verification', 'supplier_check', 'contractor_check', 'developer_check', 'property_onboarding'];

function CaseView() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get('tab') ?? 'tasks';
  const task = sp.get('task');
  const { client } = useSession();
  const c = useGet<CaseDetail>(`/v1/cases/${id}`);
  const act = useAct();
  const go = (q: Record<string, string>) => router.replace(`/cases/${id}?${new URLSearchParams({ tab, ...(task ? { task } : {}), ...q })}`, { scroll: false });
  if (c.isLoading) return <Skeleton lines={8} />;
  if (!c.data) return <ProblemBox error={c.error ?? 'Case not found.'} />;
  const x = c.data;
  const reload = () => { c.mutate(); };
  const isOpen = ['paid', 'in_progress', 'on_hold', 'in_review'].includes(x.status);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/cases', label: 'Cases' }} title={<><span className="mono" style={{ fontSize: '0.55em', display: 'block' }}>{x.reference}</span>{x.title}</>}
        chips={<>
          <span className="chip">{words(x.product_line)} v{x.template_version}</span>
          <span className="chip">{words(x.status)}</span>
          {x.risk_flag ? <span className="chip chip-ink">Risk flag</span> : <span className="chip">Risk: clear</span>}
          {x.outcome ? <span className="chip">{words(x.outcome)}</span> : null}
        </>}
        sub={<>Client {x.client?.name ?? '—'} · case manager {x.case_manager?.name ?? '—'} · opened {day(x.created_at)}</>}
        actions={isOpen ? <>
          {x.status === 'paid' ? <Button variant="primary" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/cases/${id}/accept`).then(reload), 'Case accepted. Tasks created.')}>Accept case</Button> : null}
          {x.status === 'on_hold' ? <Button variant="dark" size="sm" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/cases/${id}/resume`).then(reload), 'Case resumed.')}>Resume</Button>
            : <ActionForm label="Pause" path={`/v1/cases/${id}/hold`} fields={[{ name: 'reason', label: 'Reason (staff only)', type: 'textarea', required: true }, { name: 'client_message', label: 'What the client is told', type: 'textarea' }]} onDone={reload} submitLabel="Pause case" />}
          <ActionForm label="Cancel case" path={`/v1/cases/${id}/cancel`} title="Cancel this case" fields={[
            { name: 'reason', label: 'Reason', type: 'textarea', required: true },
            { name: 'refund_decision', label: 'Refund', type: 'select', required: true, options: [{ value: 'refund', label: 'Refund the fee' }, { value: 'no_refund', label: 'No refund' }] },
            { name: 'refund_amount', label: 'Refund amount (leave empty for the full fee)', type: 'money' },
          ]} body={(v) => ({ reason: v.reason, refund_decision: v.refund_decision, ...(v.refund_amount ? { refund_amount: v.refund_amount } : {}) })}
            onDone={reload} submitLabel="Cancel case" intro="A refund goes back through the payment provider to the original payment method." />
          {VERIFY_LINES.includes(x.product_line) && x.status === 'in_progress' ? (
            <ActionForm label="Record the decision" variant="dark" path={`/v1/cases/${id}/decisions`} fields={[
              { name: 'outcome', label: 'Outcome', type: 'select', required: true, options: [{ value: 'verified', label: 'Verified' }, { value: 'not_verified', label: 'Not verified' }] },
              { name: 'note', label: 'Note', type: 'textarea' },
            ]} onDone={reload} submitLabel="Save decision" />
          ) : null}
        </> : null} />
      <ProblemBox error={act.error} />
      {x.status === 'on_hold' ? <Blocked title="On hold">{x.hold_reason}</Blocked> : null}
      {x.status === 'cancelled' ? <Blocked title="Cancelled">{x.cancel_reason} · {words(x.refund_decision)}</Blocked> : null}
      <div className="grid2">
        <Panel title="Client sees now">
          {x.latest_status ? <>
            <p style={{ margin: 0, fontSize: 17 }}>&ldquo;{x.latest_status.text}&rdquo;</p>
            <div className="mono muted" style={{ fontSize: 12 }}>{day(x.latest_status.message_date)}{x.latest_status.next_expected_date ? ` · next by ${day(x.latest_status.next_expected_date)}` : ''}</div>
          </> : <p className="muted" style={{ margin: 0 }}>No status message yet.</p>}
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>Messages come from templates as tasks close.</p>
        </Panel>
        <Panel title="Reports and links">
          {x.reports.length ? (
            <div className="rows">
              {x.reports.map((r) => (
                <Link key={r.id} href={`/reports/${r.id}`} className="rowlink"><div className="main"><div className="title mono">{r.reference} v{r.version}</div></div><span className="chip">{words(r.status)}</span></Link>
              ))}
            </div>
          ) : <p className="muted" style={{ margin: 0 }}>No report yet.</p>}
          <div className="row">
            {x.asset ? <Link className="btn btn-ghost btn-sm" href={`/geo/assets/${x.asset}`}>Plot and map</Link> : null}
            {x.parent_case ? <Link className="btn btn-ghost btn-sm" href={`/cases/${x.parent_case}`}>Parent case</Link> : null}
          </div>
        </Panel>
      </div>
      <div className="tabs-scroll"><Tabs items={TABS} current={tab} onChange={(k) => go({ tab: k })} /></div>
      {tab === 'tasks' ? <CaseTasks c={x} selected={task} onSelect={(t) => go({ tab: 'tasks', task: t })} reload={reload} /> : null}
      {tab === 'client' ? <CaseComms c={x} reload={reload} /> : null}
      {tab === 'parties' ? <CaseParties c={x} /> : null}
      {tab === 'searches' ? <CaseSearches c={x} reload={reload} /> : null}
      {tab === 'costs' ? <CaseCosts c={x} /> : null}
      {tab === 'safety' ? <CaseSafety c={x} /> : null}
      {act.toast}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton lines={8} />}><CaseView /></Suspense>;
}

