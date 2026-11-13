'use client';
/* My work · SCR-BO-02 · W-11. Money first: releases past their clock, client-approved releases waiting for staff,
 * margin alerts. Then tasks: overdue, due this week, waiting on others (FR-CASE-005). */
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { Empty, Field, Input, ProblemBox, Select, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { ClockChip, day, money, Panel, words } from '@/components/core/kit';
import type { Approval, Instruction, Page, Task } from '@/components/core/types';

type Conversion = { id: string; escrow: string; status: string; from_amount: string; to_amount: string; applied_rate: string; margin_pct: string | null; created_at: string; quote: { from_currency: string; to_currency: string } | null };

function lateness(t: Task): string {
  const ms = new Date(t.due_at).getTime() - Date.now();
  const d = Math.round(Math.abs(ms) / 86400000);
  if (ms < 0) return d <= 0 ? 'Due today, late' : `${d} day${d === 1 ? '' : 's'} late`;
  return d === 0 ? 'Due today' : `Due in ${d} day${d === 1 ? '' : 's'}`;
}

export default function MyWork() {
  const { me, hasRole } = useSession();
  const [owner, setOwner] = useState<'all' | 'me' | 'unassigned'>('all');
  const [step, setStep] = useState('');
  const [q, setQ] = useState('');
  const query = owner === 'me' ? { owner: me?.id } : owner === 'unassigned' ? { owner: 'unassigned' } : {};
  const queue = useGet<Page<Task>>('/v1/work-queue', query, { refreshInterval: 60000 });
  const isMoney = hasRole('CM', 'RV', 'AD');
  const sendLate = useGet<Page<Instruction>>(isMoney ? '/v1/release-instructions' : null, { clock: 'send_overdue' });
  const bankLate = useGet<Page<Instruction>>(isMoney ? '/v1/release-instructions' : null, { clock: 'bank_overdue' });
  const dueToday = useGet<Page<Instruction>>(isMoney ? '/v1/release-instructions' : null, { clock: 'due_today' });
  const waitingStaff = useGet<Page<Instruction>>(hasRole('CM', 'RV', 'AD', 'RR') ? '/v1/release-instructions' : null, { status: 'pending_approval' });
  const margin = useGet<Page<Conversion>>(isMoney ? '/v1/fx-conversions' : null, { status: 'outside' });
  const approvals = useGet<Page<Approval>>('/v1/approvals');

  const tasks = useMemo(() => {
    const all = queue.data?.items ?? [];
    const needle = q.trim().toLowerCase();
    return all.filter((t) => (!step || t.step_key === step) && (!needle || `${t.case_reference} ${t.title} ${t.assignee?.name ?? ''}`.toLowerCase().includes(needle)));
  }, [queue.data, step, q]);
  const steps = useMemo(() => Array.from(new Map((queue.data?.items ?? []).map((t) => [t.step_key, t.title])).entries()).sort((a, b) => a[1].localeCompare(b[1])), [queue.data]);
  const weekEnd = Date.now() + 7 * 86400000;
  const overdue = tasks.filter((t) => t.is_overdue);
  const thisWeek = tasks.filter((t) => !t.is_overdue && !t.waiting_for.length && new Date(t.due_at).getTime() <= weekEnd);
  const waiting = tasks.filter((t) => !t.is_overdue && (t.waiting_for.length > 0 || new Date(t.due_at).getTime() > weekEnd));
  const [showWaiting, setShowWaiting] = useState(false);

  const late = [...(sendLate.data?.items ?? []), ...(bankLate.data?.items ?? [])];
  const clientApproved = (waitingStaff.data?.items ?? []).filter((i) => i.client_approved_at && !i.approvals.some((a) => a.approver === me?.full_name));
  const money_rows = [...late, ...(dueToday.data?.items ?? []).filter((i) => !late.some((l) => l.id === i.id)), ...clientApproved.filter((i) => !late.some((l) => l.id === i.id))];
  const mine = (t: Task) => t.assignee?.id === me?.id || t.second_assignee?.id === me?.id || (!t.assignee && me?.roles.includes(t.owner_role));

  const row = (t: Task, isLate: boolean) => (
    <Link key={t.id} href={`/cases/${t.case}?task=${t.id}`} className={`rowlink ${isLate && mine(t) ? 'late' : ''}`}>
      <div className="main">
        <div className="mono" style={{ fontSize: 12 }}>{t.case_reference}</div>
        <div className="title">{t.title}</div>
        <div className="meta">{t.assignee ? `${t.assignee.name}${t.second_assignee ? ` + ${t.second_assignee.name}` : ''}` : `Unassigned · needs ${t.owner_role}`}{t.waiting_for.length ? ` · waiting for ${t.waiting_for.map(words).join(', ').toLowerCase()}` : ''}</div>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <span className={`chip ${isLate && mine(t) ? 'chip-orange' : ''}`}>{isLate ? '! ' : ''}{lateness(t)}</span>
        <span className="mono" style={{ fontSize: 12 }}>{day(t.due_at)}</span>
      </div>
    </Link>
  );

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div>
        <p className="label">My work · {queue.data ? `${tasks.length} open` : '…'}</p>
        <h1 style={{ marginBottom: 0 }}>Good to see you, {me?.full_name.split(' ')[0]}.</h1>
      </div>

      {isMoney ? (
        <Panel title="Money waiting on staff" actions={<Link href="/escrow?tab=releases" className="btn btn-ghost btn-sm">All releases</Link>}>
          {sendLate.isLoading || waitingStaff.isLoading ? <Skeleton lines={2} /> : money_rows.length ? (
            <div className="rows">
              {money_rows.map((i) => {
                const overdue = i.clock?.state === 'send_overdue' || i.clock?.state === 'bank_overdue';
                return (
                  <Link key={i.id} href={`/escrow/releases/${i.id}`} className={`rowlink ${overdue ? 'late' : ''}`}>
                    <div className="main">
                      <div className="mono" style={{ fontSize: 12 }}>{i.escrow_reference}</div>
                      <div className="title">{words(i.kind)} {money(i.amount, i.currency)} to {i.payee_name || 'payee'}</div>
                      <div className="meta">{i.client_approved_at ? `Client approved ${day(i.client_approved_at)}` : words(i.status)} · approval {i.approvals.length} of 2</div>
                    </div>
                    <ClockChip clock={i.clock} />
                  </Link>
                );
              })}
            </div>
          ) : <p className="muted" style={{ margin: 0 }}>No release is late or waiting for staff.</p>}
          {margin.data?.items.length ? (
            <div className="rows">
              {margin.data.items.map((c) => (
                <Link key={c.id} href={`/escrow/${c.escrow}?tab=fx`} className="rowlink late">
                  <div className="main">
                    <div className="title">Conversion outside the programme margin</div>
                    <div className="meta mono">{c.quote ? `${c.quote.from_currency} ${c.from_amount} → ${c.quote.to_currency} ${c.to_amount}` : `${c.from_amount} → ${c.to_amount}`} at {c.applied_rate}</div>
                  </div>
                  <span className="chip chip-orange">Raise with the bank</span>
                </Link>
              ))}
            </div>
          ) : null}
        </Panel>
      ) : null}

      <Panel title="Waiting for your approval" actions={<Link href="/approvals" className="btn btn-ghost btn-sm">All approvals</Link>}>
        {approvals.isLoading ? <Skeleton lines={2} /> : approvals.data?.items.length ? (
          <div className="rows">
            {approvals.data.items.slice(0, 6).map((a) => (
              <Link key={a.id} href={`/approvals/${a.id}`} className="rowlink">
                <div className="main"><div className="label">{words(a.subject_type)}</div><div className="title">{a.summary || a.subject_id}</div></div>
                <span className="chip">{a.approvals.length} of {a.required}</span>
              </Link>
            ))}
          </div>
        ) : <p className="muted" style={{ margin: 0 }}>No approvals are waiting for you.</p>}
      </Panel>

      <section className="stack" aria-label="Tasks">
        <div className="filters">
          <Field label="Owner">
            <Select value={owner} onChange={(e) => setOwner(e.target.value as typeof owner)}>
              <option value="all">Everyone</option><option value="me">Mine</option><option value="unassigned">Unassigned</option>
            </Select>
          </Field>
          <Field label="Step">
            <Select value={step} onChange={(e) => setStep(e.target.value)}>
              <option value="">All steps</option>
              {steps.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </Select>
          </Field>
          <Field label="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Case or step" /></Field>
        </div>
        <ProblemBox error={queue.error} />
        {queue.isLoading ? <Skeleton lines={5} /> : !tasks.length ? <Empty>Nothing due. New cases appear here when paid.</Empty> : (
          <>
            <h2 style={{ fontSize: 16, margin: '6px 0 0' }} className="label">Overdue ({overdue.length})</h2>
            <div className="rows">{overdue.length ? overdue.map((t) => row(t, true)) : <p className="muted">Nothing is late.</p>}</div>
            <h2 style={{ fontSize: 16, margin: '6px 0 0' }} className="label">Due this week ({thisWeek.length})</h2>
            <div className="rows">{thisWeek.length ? thisWeek.map((t) => row(t, false)) : <p className="muted">Nothing else is due this week.</p>}</div>
            <div className="spread">
              <h2 style={{ fontSize: 16, margin: '6px 0 0' }} className="label">Waiting on others ({waiting.length})</h2>
              {waiting.length ? <button className="linkish" onClick={() => setShowWaiting(!showWaiting)}>{showWaiting ? 'Hide' : 'Show'}</button> : null}
            </div>
            {showWaiting ? <div className="rows">{waiting.map((t) => row(t, false))}</div> : null}
          </>
        )}
      </section>
    </div>
  );
}
