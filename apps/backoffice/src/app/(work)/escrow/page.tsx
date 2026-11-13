'use client';
/* Escrow · SCR-BO-10: escrows with the release clock chip; release instructions by clock; bank reconciliation
 * (SCR-BO-13): bank events to check, statement imports and unmatched lines, bank positions and mismatches. */
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useMemo, useState } from 'react';
import { Button, call, Empty, Field, Input, ProblemBox, Select, Skeleton, Tabs, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, ClockChip, day, dayTime, Head, money, Panel, useAct, words } from '@/components/core/kit';
import type { BankEvent, EscrowRow, Instruction, Page } from '@/components/core/types';

const STATUSES = ['proposed', 'agreed', 'funded', 'ready_to_release', 'client_approved', 'release_approved', 'partly_released', 'released', 'frozen', 'cancelled'];
const KINDS = ['purchase', 'construction', 'offplan', 'project_fund', 'held_funds', 'repair', 'event'];
type StatementFile = { id: string; country: string; account_kind: string; sha256: string; original_name: string; line_count: number; matched_count: number; unmatched_count: number; created_at: string };
type Line = { id: string; line_no: number; booked_on: string; kind: string; amount: string; currency: string; virtual_account_ref: string; bank_reference: string; counterparty_name: string; narrative: string; match_status: string; note: string };
type Position = { id: string; escrow: string; virtual_account_ref: string; as_of: string; reported_held_amount: string; currency: string; source: string; derived_held_at_bank: string; status: string; resolution_note: string; created_at: string };

function Escrows() {
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('');
  const [q, setQ] = useState('');
  const list = useGet<Page<EscrowRow>>('/v1/escrows', { limit: 100, ...(status ? { status } : {}), ...(kind ? { kind } : {}) });
  const clocks = useGet<Page<Instruction>>('/v1/release-instructions', { clock: 'in_progress' });
  const byEscrow = useMemo(() => {
    const m = new Map<string, Instruction>();
    const rank = (s?: string) => (s === 'send_overdue' || s === 'bank_overdue' ? 0 : s === 'running' ? 1 : 2);
    for (const i of clocks.data?.items ?? []) {
      const cur = m.get(i.escrow);
      if (!cur || rank(i.clock?.state) < rank(cur.clock?.state)) m.set(i.escrow, i);
    }
    return m;
  }, [clocks.data]);
  const needle = q.trim().toLowerCase();
  const rows = (list.data?.items ?? []).filter((e) => !needle || `${e.reference} ${e.title}`.toLowerCase().includes(needle));
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{STATUSES.map((s) => <option key={s} value={s}>{words(s)}</option>)}</Select></Field>
        <Field label="Kind"><Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All</option>{KINDS.map((s) => <option key={s} value={s}>{words(s)}</option>)}</Select></Field>
        <Field label="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Reference or title" /></Field>
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={6} /> : rows.length ? (
        <div className="rows">
          {rows.map((e) => {
            const ins = byEscrow.get(e.id);
            return (
              <Link key={e.id} href={`/escrow/${e.id}`} className="rowlink">
                <div className="main">
                  <div className="mono" style={{ fontSize: 12 }}>{e.reference} · {words(e.kind)}</div>
                  <div className="title">{e.title}</div>
                  <div className="meta">{money(e.agreed_price?.amount, e.agreed_price?.currency)} · opened {day(e.created_at)}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {e.status === 'frozen' ? <span className="chip chip-ink">🔒 Frozen</span> : <span className="chip">{words(e.status)}</span>}
                  {ins ? <ClockChip clock={ins.clock} /> : null}
                </div>
              </Link>
            );
          })}
        </div>
      ) : <Empty>No escrows match.</Empty>}
    </div>
  );
}

function Releases() {
  const [clock, setClock] = useState('in_progress');
  const list = useGet<Page<Instruction>>('/v1/release-instructions', clock.startsWith('status:') ? { status: clock.slice(7), limit: 100 } : { clock });
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Show">
          <Select value={clock} onChange={(e) => setClock(e.target.value)}>
            <option value="in_progress">All in progress</option><option value="send_overdue">Overdue: not sent</option><option value="bank_overdue">Overdue: bank not paid</option>
            <option value="due_today">Due to send today</option><option value="status:pending_approval">Waiting for staff</option><option value="status:awaiting_client">Waiting for the client</option>
            <option value="status:confirmed">Paid</option>
          </Select>
        </Field>
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={5} /> : list.data?.items.length ? (
        <div className="rows">
          {list.data.items.map((i) => (
            <Link key={i.id} href={`/escrow/releases/${i.id}`} className={`rowlink ${i.clock?.state === 'send_overdue' || i.clock?.state === 'bank_overdue' ? 'late' : ''}`}>
              <div className="main">
                <div className="mono" style={{ fontSize: 12 }}>{i.escrow_reference} · {words(i.kind)}</div>
                <div className="title">{money(i.amount, i.currency)} to {i.payee_name || 'the source account'}</div>
                <div className="meta">{i.subject_label || i.reason || '—'} · {words(i.status)} · approval {i.approvals.length} of 2</div>
              </div>
              <ClockChip clock={i.clock} />
            </Link>
          ))}
        </div>
      ) : <Empty>Nothing in this list.</Empty>}
    </div>
  );
}

function Bank() {
  const { client } = useSession();
  const events = useGet<Page<BankEvent>>('/v1/bank-events', { status: 'pending_check' });
  const files = useGet<Page<StatementFile>>('/v1/bank-statements');
  const positions = useGet<Page<Position>>('/v1/bank-positions', { status: 'mismatch' });
  const [open, setOpen] = useState<string | null>(null);
  const lines = useGet<Line[]>(open ? `/v1/bank-statements/${open}/unmatched` : null);
  const [csv, setCsv] = useState<{ name: string; text: string } | null>(null);
  const [kind, setKind] = useState('escrow');
  const act = useAct();
  return (
    <div className="stack" style={{ gap: 16 }}>
      <Panel title="Bank events to check">
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>A deposit or confirmation entered by hand counts only after a second person checks it against the bank&apos;s proof.</p>
        <ProblemBox error={events.error} />
        {events.isLoading ? <Skeleton /> : events.data?.items.length ? (
          <div className="rows">
            {events.data.items.map((ev) => (
              <div key={ev.id} className="rowlink">
                <div className="main">
                  <div className="title">{words(ev.kind)} {money(ev.amount, ev.currency)}</div>
                  <div className="meta mono">ref {ev.bank_reference} · {ev.virtual_account_ref ?? 'no reference'} · {dayTime(ev.occurred_at)}{ev.source_account_last4 ? ` · from ${ev.source_bank_name} ..${ev.source_account_last4}` : ''}{ev.misdirected ? ' · credited to another reference' : ''}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {ev.escrow ? <Link className="btn btn-ghost btn-sm" href={`/escrow/${ev.escrow}`}>Escrow</Link> : null}
                  <Button size="sm" variant="primary" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/bank-events/${ev.id}/check`, { confirm: true }).then(() => events.mutate()), 'Checked and confirmed.')}>Confirm</Button>
                  <ActionForm label="Reject" path={`/v1/bank-events/${ev.id}/check`} fields={[{ name: 'reason', label: 'What does not match the proof', type: 'textarea', required: true }]} body={(v) => ({ confirm: false, reason: v.reason })} onDone={() => events.mutate()} submitLabel="Reject" />
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>Nothing waits for a check.</Empty>}
        <ProblemBox error={act.error} />
      </Panel>

      <Panel title="Bank statements">
        <form className="filters" onSubmit={async (e) => { e.preventDefault(); if (!csv) return; const ok = await act.run(() => call(client, 'POST', '/v1/bank-statements', { country: 'GH', content: csv.text, original_name: csv.name, account_kind: kind }), 'Statement imported and matched.'); if (ok !== undefined) { setCsv(null); files.mutate(); } }}>
          <Field label="Statement file (CSV from the bank)"><input className="input" type="file" accept=".csv,text/csv" onChange={async (e) => { const f = e.target.files?.[0]; setCsv(f ? { name: f.name, text: await f.text() } : null); }} required /></Field>
          <Field label="Account"><Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="escrow">Escrow</option><option value="held_funds">Held funds</option><option value="owner_rent">Owner rent</option></Select></Field>
          <Button type="submit" variant="dark" busy={act.busy} disabled={!csv}>Import</Button>
        </form>
        {files.isLoading ? <Skeleton /> : files.data?.items.length ? (
          <div className="rows">
            {files.data.items.map((f) => (
              <div key={f.id} className="stack" style={{ gap: 6 }}>
                <div className="rowlink">
                  <div className="main"><div className="title">{f.original_name}</div><div className="meta mono">{dayTime(f.created_at)} · {words(f.account_kind)} · sha256 {f.sha256.slice(0, 12)}…</div></div>
                  <div className="row" style={{ gap: 6 }}>
                    <span className="chip">{f.matched_count} of {f.line_count} matched</span>
                    {f.unmatched_count ? <Button size="sm" variant="ghost" onClick={() => setOpen(open === f.id ? null : f.id)}>{open === f.id ? 'Hide' : `${f.unmatched_count} unmatched`}</Button> : null}
                  </div>
                </div>
                {open === f.id ? (lines.isLoading ? <Skeleton /> : (
                  <div className="rows" style={{ paddingLeft: 12 }}>
                    {(lines.data ?? []).map((l) => (
                      <div key={l.id} className="rowlink"><div className="main"><div className="title">Line {l.line_no}: {words(l.kind)} {money(l.amount, l.currency)}</div><div className="meta mono">{l.booked_on} · ref {l.bank_reference} · {l.virtual_account_ref || 'no escrow reference'} · {l.counterparty_name}</div><div className="meta">{l.narrative}{l.note ? ` · ${l.note}` : ''}</div></div><span className="chip">{words(l.match_status)}</span></div>
                    ))}
                  </div>
                )) : null}
              </div>
            ))}
          </div>
        ) : <Empty>No statement imported yet.</Empty>}
      </Panel>

      <Panel title="Bank positions that do not match">
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>The bank&apos;s figure for an escrow differs from its confirmed events. Releases on that escrow stay blocked until a reviewer resolves it with the bank&apos;s written explanation (RUL-34).</p>
        {positions.isLoading ? <Skeleton /> : positions.data?.items.length ? (
          <div className="rows">
            {positions.data.items.map((p) => (
              <div key={p.id} className="rowlink">
                <div className="main">
                  <div className="mono" style={{ fontSize: 12 }}>{p.virtual_account_ref} · as of {day(p.as_of)}</div>
                  <div className="title mono">Bank {money(p.reported_held_amount, p.currency)} · events {money(p.derived_held_at_bank, p.currency)}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <Link className="btn btn-ghost btn-sm" href={`/escrow/${p.escrow}?tab=bank`}>Escrow</Link>
                  <ActionForm label="Resolve" variant="dark" path={`/v1/bank-positions/${p.id}/resolve`} upload={{ subject_type: 'escrow', subject_id: p.escrow, role: 'bank_explanation' }} fields={[
                    { name: 'note', label: "The bank's explanation", type: 'textarea', required: true }, { name: 'evidence_id', label: "The bank's letter or message", type: 'file', required: true },
                  ]} onDone={() => positions.mutate()} submitLabel="Resolve" intro="A second person checks the resolution before releases open again." />
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>Every bank position matches.</Empty>}
      </Panel>
      {act.toast}
    </div>
  );
}

function EscrowHome() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get('tab') ?? 'escrows';
  const { hasRole } = useSession();
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head title="Escrow" sub="Tenmina never holds client money. The partner bank does; money moves only on two staff approvals after the client." actions={<>
        <Link className="btn btn-ghost btn-sm" href="/escrow/fx">Rates and accounts</Link>
        {hasRole('CM', 'RV') ? (
          <ActionForm label="+ New escrow" variant="dark" path="/v1/escrows" fields={[
            { name: 'kind', label: 'Kind', type: 'select', required: true, options: KINDS.map((k) => ({ value: k, label: words(k) })) },
            { name: 'title', label: 'Title', required: true }, { name: 'client_id', label: 'Client ID', required: true },
            { name: 'amount', label: 'Agreed price', type: 'money' }, { name: 'currency', label: 'Currency', initial: 'GHS' },
            { name: 'report_id', label: 'Released report ID (its conditions are copied)' }, { name: 'case_id', label: 'Case ID' }, { name: 'asset_id', label: 'Property ID' },
            { name: 'held_back_amount', label: 'Held back until a later condition', type: 'money' }, { name: 'held_back_condition', label: 'That condition' },
          ]} body={(v) => ({ kind: v.kind, country: 'GH', title: v.title, client_id: v.client_id, ...(v.amount ? { agreed_price: { amount: v.amount, currency: String(v.currency || 'GHS').toUpperCase() } } : {}), ...(v.report_id ? { report_id: v.report_id } : {}), ...(v.case_id ? { case_id: v.case_id } : {}), ...(v.asset_id ? { asset_id: v.asset_id } : {}), held_back_amount: v.held_back_amount || 0, held_back_condition: v.held_back_condition || '' })}
            onDone={(out) => { const x = out as { id?: string }; if (x?.id) router.push(`/escrow/${x.id}`); }} submitLabel="Create escrow" intro="Parties, the virtual account and the terms version are added on the escrow next." />
        ) : null}
      </>} />
      <div className="tabs-scroll"><Tabs items={[{ key: 'escrows', label: 'Escrows' }, { key: 'releases', label: 'Releases' }, { key: 'bank', label: 'Bank and reconciliation' }]} current={tab} onChange={(k) => router.replace(`/escrow?tab=${k}`)} /></div>
      {tab === 'escrows' ? <Escrows /> : tab === 'releases' ? <Releases /> : <Bank />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton />}><EscrowHome /></Suspense>;
}
