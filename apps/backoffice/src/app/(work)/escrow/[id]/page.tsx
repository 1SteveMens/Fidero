'use client';
/* Escrow detail · SCR-BO-11: parties and acceptances, the virtual account, conditions, bank events and their check,
 * the statement built only from bank-confirmed events, holds and freezes, cancellation, releases and exchange. */
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Blocked, Button, call, Empty, ProblemBox, Skeleton, Tabs, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, ClockChip, day, dayTime, DoneSlot, Facts, Head, iso, money, MySlot, OpenSlot, Panel, useAct, words } from '@/components/core/kit';
import type { Approval, Escrow, Instruction, Page } from '@/components/core/types';

type Line = { at: string; type: string; kind: string; id: string; amount: number; currency: string; bank_reference: string; status: string; counts: boolean; subject_label: string; payee: string | null };
type Conversion = { id: string; route: string; from_amount: string; to_amount: string; applied_rate: string; applied_fees: string | null; reference_rate: string | null; margin_pct: string | null; programme_rate: string | null; short_of_quote: string | null; status: string; findings: unknown; claim_amount: string | null; resolution_note: string; created_at: string; quote: { id: string; from_currency: string; to_currency: string; offered_rate: string; expected_to_amount: string; margin_pct: string; accepted_at: string | null } | null };
type Quote = { id: string; from_currency: string; from_amount: string; to_currency: string; offered_rate: string; reference_rate: string; margin_pct: string; fees_total_to: string; expected_to_amount: string; expires_at: string; accepted_at: string | null; shown_text: string };

const STAFF_CAN = (h: (...r: string[]) => boolean) => h('CM', 'RV');

function Overview({ e, reload }: { e: Escrow; reload: () => void }) {
  const { client, hasRole, me } = useSession();
  const act = useAct();
  const isStaff = STAFF_CAN(hasRole);
  const cancelApprovals = useGet<Page<Approval>>(e.cancel_requested_at ? '/v1/approvals' : null, { subject_type: 'escrow_cancel', status: 'open' });
  const cancelReq = cancelApprovals.data?.items.find((a) => a.subject_id === e.id);
  const pi = e.payment_instructions as Record<string, string | boolean | undefined>;
  const payeeParties = e.parties.filter((p) => p.payee);
  return (
    <div className="stack" style={{ gap: 16 }}>
      {e.agreement_blockers.length ? (
        <Panel title="Before the terms are agreed">
          {e.agreement_blockers.map((b, i) => <div key={i} className="row" style={{ gap: 8 }}><span className="gate-mark gate-no" aria-hidden>✕</span><span><span className="mono muted" style={{ fontSize: 11 }}>{b.rule}</span> {b.message}</span></div>)}
        </Panel>
      ) : null}
      <div className="grid2">
        <Panel title="Terms">
          <Facts items={[
            ['Kind', words(e.kind)], ['Price', money(e.agreed_price?.amount, e.agreed_price?.currency)],
            ['Held back', Number(e.held_back_amount) ? `${money(e.held_back_amount, e.currency)} until ${e.held_back_condition}` : 'None'],
            ['Currency held', e.currency], ['Conversion', e.conversion_choice === 'at_release' ? `Held until release${e.fx_buffer_pct ? ` (+${e.fx_buffer_pct}% buffer)` : ''}` : 'Converted on arrival'],
            ['Agreed', day(e.agreed_at)], ['Funded', day(e.funded_at)],
            ...(['purchase', 'offplan'].includes(e.kind) ? [['Fresh search result', day(e.fresh_search_result_date)], ['Site check', day(e.site_check_date)]] as [string, string][] : []),
          ]} />
          <div className="row">
            {e.case_id ? <Link className="btn btn-ghost btn-sm" href={`/cases/${e.case_id}`}>Case</Link> : null}
            {e.report_id ? <Link className="btn btn-ghost btn-sm" href={`/reports/${e.report_id}`}>Report</Link> : null}
            {e.asset_id ? <Link className="btn btn-ghost btn-sm" href={`/geo/assets/${e.asset_id}`}>Plot</Link> : null}
            {isStaff && ['purchase', 'offplan'].includes(e.kind) ? (
              <ActionForm label="Record fresh search" path={`/v1/escrows/${e.id}/fresh-search`} fields={[
                { name: 'case_id', label: 'Fresh-search case ID', required: true }, { name: 'registry_result_date', label: "Date of the registry's result", type: 'date', required: true }, { name: 'site_check_date', label: 'Date of the site check', type: 'date', required: true },
              ]} onDone={reload} submitLabel="Save" intro="The window counts from the registry's result date and the site check date (RUL-07)." />
            ) : null}
          </div>
        </Panel>
        <Panel title="Account at the bank">
          {pi?.available ? (
            <Facts items={[['Bank', String(pi.bank_name ?? '')], ['Account name', String(pi.account_name ?? '')], ['Escrow reference', <span key="r" className="mono">{String(pi.virtual_account_ref ?? '')}</span>], ['Pay with reference', <span key="p" className="mono">{String(pi.reference ?? '')}</span>]]} />
          ) : <p className="muted" style={{ margin: 0 }}>No virtual account at the bank yet. The client cannot pay in until there is one.</p>}
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>Clients see only the bank&apos;s payment instructions, never a Tenmina account.</p>
          {isStaff ? (
            <div className="row">
              <ActionForm label={e.virtual_account_ref ? 'Change reference' : 'Record virtual account'} path={`/v1/escrows/${e.id}/virtual-account`} fields={[{ name: 'virtual_account_ref', label: "The bank's virtual account number or reference", required: true }, { name: 'programme_account_id', label: 'Programme account ID (if not the default)' }]}
                body={(v) => ({ virtual_account_ref: v.virtual_account_ref, ...(v.programme_account_id ? { programme_account_id: v.programme_account_id } : {}) })} onDone={reload} submitLabel="Save" />
              <ActionForm label="Add foreign-currency account" path={`/v1/escrows/${e.id}/fx-accounts`} fields={[{ name: 'currency', label: 'Currency', required: true, placeholder: 'USD' }, { name: 'virtual_account_ref', label: 'Virtual account reference', required: true }]}
                body={(v) => ({ currency: String(v.currency).toUpperCase(), virtual_account_ref: v.virtual_account_ref })} onDone={reload} submitLabel="Save" />
            </div>
          ) : null}
        </Panel>
      </div>

      <Panel title="Parties" actions={isStaff ? (
        <ActionForm label="+ Add party" path={`/v1/escrows/${e.id}/parties`} fields={[
          { name: 'role', label: 'Role', type: 'select', required: true, options: ['seller', 'developer', 'contractor', 'supplier', 'vendor'].map((x) => ({ value: x, label: words(x) })) },
          { name: 'name', label: 'Name', required: true }, { name: 'payee_id', label: 'Verified payee ID', hint: 'From Payees. Money goes only to a verified payee.' },
          { name: 'must_accept', label: 'Must accept the terms', type: 'checkbox', initial: true },
        ]} body={(v) => ({ role: v.role, name: v.name, must_accept: !!v.must_accept, ...(v.payee_id ? { payee_id: v.payee_id } : {}) })} onDone={reload} submitLabel="Add party" />
      ) : null}>
        <div className="rows">
          {e.parties.map((p) => (
            <div key={p.id} className="rowlink">
              <div className="main"><div className="label">{words(p.role)}</div><div className="title">{p.name}</div>{p.payee ? <div className="meta">🔒 Payee locked · <Link href={`/payees/${p.payee}`}>payee record</Link></div> : null}</div>
              <div className="row" style={{ gap: 6 }}>
                {p.must_accept ? (p.accepted_current_terms ? <span className="chip chip-lime">✓ Accepted terms</span> : <span className="chip">Not accepted yet</span>) : <span className="chip">No acceptance needed</span>}
                {isStaff && p.must_accept && !p.accepted_current_terms ? (
                  <ActionForm label="Record acceptance" path={`/v1/escrows/${e.id}/acceptances`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'acceptance' }} fields={[{ name: 'evidence_id', label: 'Signed acceptance', type: 'file', required: true }]}
                    body={(v) => ({ party_id: p.id, evidence_id: v.evidence_id })} onDone={reload} submitLabel="Save" intro="For a party who accepted on paper. The time and terms version are recorded." />
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title={`Conditions (${e.conditions.filter((c) => c.status === 'closed').length} of ${e.conditions.length} closed)`} actions={isStaff ? (
        <ActionForm label="+ Add condition" path={`/v1/escrows/${e.id}/conditions`} fields={[{ name: 'text', label: 'Condition', type: 'textarea', required: true }, { name: 'key', label: 'Short key' }]} onDone={reload} submitLabel="Add" />
      ) : null}>
        {e.conditions.length ? (
          <div className="rows">
            {e.conditions.map((c) => (
              <div key={c.id} className="rowlink">
                <div className="main">
                  <div className="title">{c.text}</div>
                  <div className="meta">{c.status === 'closed' ? `Closed ${dayTime(c.closed_at)}${c.closed_note ? ` · ${c.closed_note}` : ''}` : c.reopened_at ? `Reopened: ${c.reopen_reason}` : 'Open'}{c.release_part !== 'main' ? ' · held-back share' : ''}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <span className={`chip ${c.status === 'closed' ? 'chip-lime' : ''}`}>{c.status === 'closed' ? '✓ Closed' : 'Open'}</span>
                  {isStaff && c.status !== 'closed' ? (
                    <ActionForm label="Close with evidence" variant="dark" path={`/v1/escrows/${e.id}/conditions/${c.id}/close`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'condition_evidence' }} fields={[{ name: 'evidence', label: 'Evidence that satisfies it', type: 'file', required: true }, { name: 'note', label: 'Note', type: 'textarea' }]}
                      body={(v) => ({ evidence_ids: [v.evidence], note: v.note || '' })} onDone={reload} submitLabel="Close condition" />
                  ) : null}
                  {hasRole('RV') && c.status === 'closed' ? <ActionForm label="Reopen" path={`/v1/escrows/${e.id}/conditions/${c.id}/reopen`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={reload} submitLabel="Reopen" /> : null}
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>No conditions.</Empty>}
      </Panel>

      <div className="grid2">
        <Panel title="Holds and freezes" actions={hasRole('RV') ? <ActionForm label="Put on hold" path={`/v1/escrows/${e.id}/holds`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={reload} submitLabel="Hold" intro="No release or refund goes out while the hold is on." /> : null}>
          {e.freezes.length ? e.freezes.map((f) => (
            <div key={f.id} className="stack" style={{ gap: 6 }}>
              <Blocked title={f.kind === 'dispute' ? 'Frozen by a dispute' : f.kind === 'incident' ? 'Frozen after a failed re-check' : 'On hold by a reviewer'}>{f.reason} · since {day(f.frozen_at)}</Blocked>
              {hasRole('RV') && f.kind === 'reviewer_hold' ? <div><ActionForm label="Lift hold" path={`/v1/escrows/${e.id}/holds/${f.id}/lift`} fields={[{ name: 'reason', label: 'Why it can lift', type: 'textarea', required: true }]} onDone={reload} submitLabel="Lift" /></div> : null}
            </div>
          )) : <p className="muted" style={{ margin: 0 }}>No hold or freeze.</p>}
        </Panel>
        <Panel title="Cancellation">
          {e.cancel_requested_at ? (
            <div className="stack">
              <Blocked title="Cancellation requested">{e.cancel_reason} · {day(e.cancel_requested_at)}. Only refunds go out, to the account the money came from.</Blocked>
              {cancelReq ? (
                <div className="ground-ink stack" style={{ borderRadius: 16, padding: 14 }}>
                  <div className="grid2">
                    {[0, 1].map((n) => {
                      const a = cancelReq.approvals[n];
                      const title = `Approval ${n + 1} of 2`;
                      if (a) return <DoneSlot key={n} title={title} name={a.approver_name} at={a.at} decision={a.decision} />;
                      if (n === cancelReq.approvals.length && cancelReq.prepared_by !== me?.id && !cancelReq.approvals.some((x) => x.approver === me?.id)) {
                        return <MySlot key={n} title={title} holdLabel="Press and hold to approve the cancellation" confirmText="I checked the reason and the deposits myself"
                          onApprove={async () => { await call(client, 'POST', `/v1/escrows/${e.id}/cancellation-approvals`, { decision: 'approve' }); reload(); cancelApprovals.mutate(); }}
                          onReturn={async (note) => { await call(client, 'POST', `/v1/escrows/${e.id}/cancellation-approvals`, { decision: 'reject', note }); reload(); cancelApprovals.mutate(); }} returnLabel="Reject with a reason" />;
                      }
                      return <OpenSlot key={n} title={title} text={cancelReq.prepared_by === me?.id ? 'You asked for this. Two other people approve it.' : 'Waiting'} />;
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          ) : isStaff && !['released', 'cancelled'].includes(e.status) ? (
            <ActionForm label="Ask to cancel" path={`/v1/escrows/${e.id}/cancellation`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={reload} submitLabel="Ask to cancel" intro="Two staff approve a cancellation. Money is refunded only to the account it came from (RUL-29)." />
          ) : <p className="muted" style={{ margin: 0 }}>{e.status === 'cancelled' ? 'Cancelled.' : 'Not requested.'}</p>}
        </Panel>
      </div>
      {payeeParties.length === 0 && e.status !== 'proposed' ? <p className="muted" style={{ margin: 0, fontSize: 13 }}>No party has a payee yet. A release needs a verified payee.</p> : null}
      <ProblemBox error={act.error} />
    </div>
  );
}

function MoneyTab({ e, reload }: { e: Escrow; reload: () => void }) {
  const { hasRole } = useSession();
  const st = useGet<{ lines: Line[]; funds: Record<string, string>[] }>(`/v1/escrows/${e.id}/statement`);
  const isStaff = STAFF_CAN(hasRole);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <Panel title="Money at the bank" actions={isStaff ? <>
        <ActionForm label="Record a bank event" variant="dark" path={`/v1/escrows/${e.id}/bank-events`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'bank_proof' }} fields={[
          { name: 'kind', label: 'What the bank confirmed', type: 'select', required: true, options: ['deposit', 'release_confirmed', 'refund_confirmed', 'conversion_debit', 'conversion_credit', 'correction_debit'].map((x) => ({ value: x, label: words(x) })) },
          { name: 'amount', label: 'Amount', type: 'money', required: true }, { name: 'currency', label: 'Currency', initial: e.currency, required: true },
          { name: 'bank_reference', label: "Bank's reference", required: true }, { name: 'occurred_at', label: 'When', type: 'datetime' },
          { name: 'virtual_account_ref', label: 'Escrow reference the bank used', initial: e.virtual_account_ref },
          { name: 'proof_evidence_id', label: "The bank's proof", type: 'file', required: true },
          { name: 'source_bank_name', label: 'Deposit from: bank' }, { name: 'source_account_number', label: 'Deposit from: account number' }, { name: 'source_account_name', label: 'Deposit from: account name' },
          { name: 'deposit_route', label: 'Route', type: 'select', options: [{ value: 'bank_transfer', label: 'Bank transfer' }, { value: 'transfer_partner', label: 'Transfer service' }, { value: 'bank_correction', label: 'Bank correction' }] },
          { name: 'misdirected', label: 'The bank credited another escrow\'s reference', type: 'checkbox' }, { name: 'note', label: 'Note', type: 'textarea' },
        ]} body={(v) => ({ kind: v.kind, amount: { amount: v.amount, currency: String(v.currency).toUpperCase() }, bank_reference: v.bank_reference, occurred_at: iso(v.occurred_at), virtual_account_ref: v.virtual_account_ref || '', proof_evidence_id: v.proof_evidence_id,
          source_bank_name: v.source_bank_name || '', source_account_number: v.source_account_number || '', source_account_name: v.source_account_name || '', ...(v.deposit_route ? { deposit_route: v.deposit_route } : {}), misdirected: !!v.misdirected, note: v.note || '' })}
          onDone={() => { st.mutate(); reload(); }} submitLabel="Save" intro="It counts only after a second person checks it against the proof." />
        <ActionForm label="Record the bank's figure" path={`/v1/escrows/${e.id}/bank-positions`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'bank_position' }} fields={[
          { name: 'as_of', label: 'As of', type: 'date', required: true }, { name: 'amount', label: 'Amount the bank holds', type: 'money', required: true }, { name: 'currency', label: 'Currency', initial: e.currency, required: true },
          { name: 'proof_evidence_id', label: "The bank's statement or letter", type: 'file', required: true },
        ]} body={(v) => ({ as_of: v.as_of, reported_held: { amount: v.amount, currency: String(v.currency).toUpperCase() }, proof_evidence_id: v.proof_evidence_id })} onDone={() => { st.mutate(); reload(); }} submitLabel="Save" />
      </> : null}>
        {e.funds.length ? (
          <div className="rows">
            {e.funds.map((f, i) => (
              <div key={i} className="card stack" style={{ background: 'var(--color-bg)', padding: 14 }}>
                <div className="label">{String(f.currency)} · {String(f.virtual_account_ref ?? 'no reference')}</div>
                <Facts items={[
                  ['Held at the bank', <span key="h" className="mono" style={{ fontWeight: 800 }}>{money(f.held_at_bank, f.currency)}</span>],
                  ['Instructed, awaiting bank', <span key="i" className="mono">{money(f.instructed_awaiting_bank, f.currency)}</span>],
                  ['Awaiting correction', <span key="c" className="mono">{money(f.awaiting_correction, f.currency)}</span>],
                  ['Available to instruct', <span key="a" className="mono">{money(f.available_to_instruct, f.currency)}</span>],
                  ['Last bank event', dayTime(f.last_bank_event_at)],
                ]} />
              </div>
            ))}
          </div>
        ) : <p className="muted" style={{ margin: 0 }}>The bank has confirmed nothing yet.</p>}
      </Panel>
      <Panel title="Statement">
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>Built only from bank-confirmed events. Instructions not yet paid are shown but do not count.</p>
        <ProblemBox error={st.error} />
        {st.isLoading ? <Skeleton /> : st.data?.lines.length ? (
          <div className="rows">
            {st.data.lines.map((l) => (
              <div key={`${l.type}-${l.id}`} className="rowlink" style={{ opacity: l.counts ? 1 : 0.65 }}>
                <div className="main"><div className="title">{words(l.kind)}{l.payee ? ` to ${l.payee}` : ''}</div><div className="meta mono">{dayTime(l.at)}{l.bank_reference ? ` · ref ${l.bank_reference}` : ''}{l.subject_label ? ` · ${l.subject_label}` : ''}</div></div>
                <div className="row" style={{ gap: 8 }}>
                  <span className="chip">{l.counts ? words(l.status) : `${words(l.status)} · not counted`}</span>
                  <span className="mono" style={{ fontWeight: 800 }}>{money(l.amount, l.currency)}</span>
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>No lines yet.</Empty>}
      </Panel>
    </div>
  );
}

function ReleasesTab({ e }: { e: Escrow }) {
  const { hasRole } = useSession();
  const list = useGet<Instruction[]>(`/v1/escrows/${e.id}/release-instructions`);
  const payees = e.parties.filter((p) => p.payee);
  return (
    <Panel title="Release and refund instructions" actions={STAFF_CAN(hasRole) && payees.length ? (
      <ActionForm label="Prepare a release" variant="dark" path={`/v1/escrows/${e.id}/release-instructions`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'release_evidence' }} fields={[
        { name: 'payee_id', label: 'Pay', type: 'select', required: true, options: payees.map((p) => ({ value: p.payee as string, label: `${p.name} (${words(p.role).toLowerCase()})` })) },
        { name: 'kind', label: 'Kind', type: 'select', initial: 'release', options: [{ value: 'release', label: 'Release' }, { value: 'partial_release', label: 'Partial release' }] },
        { name: 'amount', label: 'Amount', type: 'money', required: true }, { name: 'currency', label: 'Currency', initial: e.currency, required: true },
        { name: 'release_part', label: 'Part', type: 'select', initial: 'main', options: [{ value: 'main', label: 'Main release' }, { value: 'held_back', label: 'Held-back share' }] },
        { name: 'holdback_amount', label: 'Hold back from this release', type: 'money' },
        { name: 'reason', label: 'Reason', type: 'textarea' }, { name: 'evidence', label: 'Supporting evidence', type: 'file' },
      ]} body={(v) => ({ payee_id: v.payee_id, kind: v.kind || 'release', amount: { amount: v.amount, currency: String(v.currency).toUpperCase() }, release_part: v.release_part || 'main', holdback_amount: v.holdback_amount || 0, reason: v.reason || '', evidence_ids: v.evidence ? [v.evidence] : [] })}
        onDone={() => list.mutate()} submitLabel="Prepare" intro="The client approves first. Then two staff with release rights approve. Money goes only to a verified payee." />
    ) : null}>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton /> : list.data?.length ? (
        <div className="rows">
          {list.data.map((i) => (
            <Link key={i.id} href={`/escrow/releases/${i.id}`} className="rowlink">
              <div className="main"><div className="title">{words(i.kind)} {money(i.amount, i.currency)} to {i.payee_name || 'the source account'}</div><div className="meta">{i.subject_label || i.reason || '—'} · {words(i.status)} · {dayTime(i.created_at)}</div></div>
              <ClockChip clock={i.clock} />
            </Link>
          ))}
        </div>
      ) : <Empty>No instructions yet.</Empty>}
    </Panel>
  );
}

function FxTab({ e }: { e: Escrow }) {
  const { client, hasRole } = useSession();
  const conv = useGet<Conversion[]>(`/v1/escrows/${e.id}/conversions`);
  const act = useAct();
  return (
    <div className="stack" style={{ gap: 16 }}>
      <Panel title="Conversions against the accepted quote" actions={STAFF_CAN(hasRole) ? (
        <ActionForm label="Get a quote" path={`/v1/escrows/${e.id}/fx-quotes`} fields={[
          { name: 'purpose', label: 'For', type: 'select', initial: 'release_conversion', options: [{ value: 'deposit', label: 'A deposit' }, { value: 'release_conversion', label: 'Converting before a release' }, { value: 'refund_conversion', label: 'A refund' }] },
          { name: 'route', label: 'Route', type: 'select', required: true, options: [{ value: 'escrow_fx_account', label: "The escrow's foreign-currency account" }, { value: 'escrow_local_account', label: "The escrow's cedi account" }, { value: 'transfer_partner', label: 'A transfer service' }] },
          { name: 'amount', label: 'Amount', type: 'money', required: true }, { name: 'currency', label: 'From currency', initial: 'USD', required: true },
        ]} body={(v) => ({ purpose: v.purpose, route: v.route, amount: { amount: v.amount, currency: String(v.currency).toUpperCase() } })}
          onDone={(q) => { const x = q as Quote; act.show(`Quote ${x.from_currency} ${x.from_amount} → ${x.to_currency} ${x.expected_to_amount} at ${x.offered_rate}. The client accepts it in the app.`); }} submitLabel="Get quote" intro="Tenmina takes no margin on the exchange. The client sees and accepts the quote." />
      ) : null}>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>Each conversion the bank makes is checked against the quote the client accepted. Outside the programme margin raises an alert (FR-ESC-023).</p>
        <ProblemBox error={conv.error ?? act.error} />
        {conv.isLoading ? <Skeleton /> : conv.data?.length ? (
          <div className="rows">
            {conv.data.map((c) => (
              <div key={c.id} className="card stack" style={{ background: 'var(--color-bg)', padding: 14 }}>
                {c.status === 'outside' ? <div className="strip-ink">Outside programme margin</div> : null}
                <div className="row mono" style={{ gap: 16, flexWrap: 'wrap' }}>
                  <span>Quote {c.quote ? `${c.quote.offered_rate} → ${c.quote.expected_to_amount} ${c.quote.to_currency}` : '—'}</span>
                  <span>Bank {c.applied_rate} → {c.to_amount}</span>
                  {c.margin_pct ? <span>margin {c.margin_pct}%</span> : null}
                  {c.short_of_quote ? <span>short {c.short_of_quote}</span> : null}
                </div>
                <div className="meta">{words(c.route)} · {dayTime(c.created_at)} · {words(c.status)}{c.resolution_note ? ` · ${c.resolution_note}` : ''}</div>
                {c.status === 'outside' ? (
                  <div className="row">
                    {hasRole('RV') ? <ActionForm label="Resolve with the bank" variant="dark" path={`/v1/fx-conversions/${c.id}/resolve`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'fx_resolution' }} fields={[
                      { name: 'note', label: "The bank's answer", type: 'textarea', required: true }, { name: 'evidence_id', label: "The bank's letter", type: 'file', required: true },
                      { name: 'claim_amount', label: 'Amount claimed back', type: 'money' }, { name: 'claim_reference', label: 'Claim reference' },
                    ]} body={(v) => ({ note: v.note, evidence_id: v.evidence_id, ...(v.claim_amount ? { claim_amount: v.claim_amount } : {}), claim_reference: v.claim_reference || '' })} onDone={() => conv.mutate()} submitLabel="Resolve" /> : null}
                  </div>
                ) : null}
                {c.status === 'resolved' ? <div><Button size="sm" variant="ghost" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/fx-conversions/${c.id}/resolution-check`).then(() => conv.mutate()), 'Resolution checked.')}>Check the resolution</Button></div> : null}
              </div>
            ))}
          </div>
        ) : <Empty>No conversions on this escrow.</Empty>}
      </Panel>
      {act.toast}
    </div>
  );
}

function EscrowView() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get('tab') ?? 'overview';
  const e = useGet<Escrow>(`/v1/escrows/${id}`);
  if (e.isLoading) return <Skeleton lines={8} />;
  if (!e.data) return <ProblemBox error={e.error ?? 'Escrow not found.'} />;
  const x = e.data;
  const reload = () => { e.mutate(); };
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/escrow', label: 'Escrow' }} title={<><span className="mono" style={{ fontSize: '0.55em', display: 'block' }}>{x.reference}</span>{x.title}</>}
        chips={<>{x.status === 'frozen' ? <span className="chip chip-ink">🔒 Frozen</span> : <span className="chip">{words(x.status)}</span>}<span className="chip">{words(x.kind)}</span><span className="chip">{money(x.agreed_price?.amount, x.agreed_price?.currency)}</span></>} />
      {x.freezes.length ? <Blocked title="Release blocked">{x.freezes.map((f) => f.reason || words(f.kind)).join(' · ')}</Blocked> : null}
      <div className="tabs-scroll"><Tabs items={[{ key: 'overview', label: 'Overview' }, { key: 'bank', label: 'Money and statement' }, { key: 'releases', label: 'Releases' }, { key: 'fx', label: 'Exchange' }]} current={tab} onChange={(k) => router.replace(`/escrow/${id}?tab=${k}`, { scroll: false })} /></div>
      {tab === 'overview' ? <Overview e={x} reload={reload} /> : tab === 'bank' ? <MoneyTab e={x} reload={reload} /> : tab === 'releases' ? <ReleasesTab e={x} /> : <FxTab e={x} />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton />}><EscrowView /></Suspense>;
}
