'use client';
/* Two-person release approval · SCR-BO-12 · W-15, on black. One sentence of who gets how much from where, the release
 * clock, the gates ticked in lime, approval 1 shown done, this person's slot outlined in orange, six code boxes, press
 * and hold. Refunds use the same screen with "Refund" wording. No "send later" control (RUL-33). */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, Button, call, ProblemBox, Skeleton, Ticket, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, ClockChip, day, dayTime, DoneSlot, Gate, money, MySlot, OpenSlot, useAct, words } from '@/components/core/kit';
import { gates } from '@/components/core/escrow/gates';
import type { Escrow, Instruction, Payee } from '@/components/core/types';

export default function ReleaseApproval() {
  const { id } = useParams<{ id: string }>();
  const { client, me, hasRole } = useSession();
  const ins = useGet<Instruction>(`/v1/release-instructions/${id}`, undefined, { refreshInterval: 30000 });
  const esc = useGet<Escrow>(ins.data ? `/v1/escrows/${ins.data.escrow}` : null);
  const payee = useGet<Payee>(ins.data?.payee && hasRole('CM', 'RV', 'AD') ? `/v1/payees/${ins.data.payee}` : null, undefined, { shouldRetryOnError: false });
  const act = useAct();
  if (ins.isLoading) return <div className="ground-ink" style={{ padding: 16, borderRadius: 20 }}><Skeleton lines={8} /></div>;
  if (!ins.data) return <ProblemBox error={ins.error ?? 'Instruction not found.'} />;
  const i = ins.data;
  const e = esc.data;
  const refund = i.kind === 'cancel_refund';
  const verb = refund ? 'Refund' : i.kind === 'conversion' ? 'Convert' : 'Pay';
  const rows = gates(i, e);
  const failing = rows.filter((g) => !g.ok);
  const myName = me?.full_name;
  const iApproved = i.approvals.some((a) => a.approver === myName && a.decision === 'approve');
  const iPrepared = i.prepared_by === me?.id;
  const canApprove = hasRole('RR');
  const reload = () => { ins.mutate(); esc.mutate(); };
  const clock = i.clock;
  const stateLine = clock?.state === 'send_overdue' ? `Overdue: not sent on the day of the last approval (due ${day(clock.send_due_on)}).`
    : clock?.state === 'bank_overdue' ? `Overdue: the bank has not confirmed payment. Expected by ${day(clock.bank_pay_due_on)}.`
      : clock?.state === 'paused_shortfall' ? 'Waiting for the client\'s top-up (RUL-36).'
        : clock?.state === 'frozen' ? `Frozen: ${clock.frozen_reason}` : clock?.staff_approval_due_on ? `Target: staff approval by ${day(clock.staff_approval_due_on)}; sent the working day of the last approval.` : '';

  const slot = (n: number) => {
    const a = i.approvals[n];
    const title = `Approval ${n + 1} of 2`;
    if (a) return <DoneSlot key={n} title={title} name={a.approver} at={a.at} decision={a.decision} />;
    if (i.status === 'pending_approval' && n === i.approvals.length) {
      if (iPrepared) return <OpenSlot key={n} title={title} text="You prepared this instruction. Two other people approve it." />;
      if (iApproved) return <OpenSlot key={n} title={title} text="You gave approval 1. A different person must give approval 2 (RUL-05)." />;
      if (!canApprove) return <OpenSlot key={n} title={title} text="Waiting for a reviewer with release rights." />;
      if (failing.length) return <OpenSlot key={n} title={title} text="Closed while a gate is open." />;
      return (
        <MySlot key={n} title={title} confirmText="I checked the evidence for each condition myself" holdLabel={n === 1 ? 'Press and hold to approve and send to the bank' : 'Press and hold to approve'}
          onApprove={async () => { await call(client, 'POST', `/v1/release-instructions/${id}/approvals`, { decision: 'approve', confirm_amount: { amount: i.amount, currency: i.currency } }); reload(); }}
          onReturn={async (note) => { await call(client, 'POST', `/v1/release-instructions/${id}/approvals`, { decision: 'reject', note }); reload(); }} />
      );
    }
    return <OpenSlot key={n} title={title} text={i.status === 'awaiting_client' ? 'Opens after the client approves.' : 'Waiting'} />;
  };

  return (
    <div className="ground-ink stack" style={{ gap: 18, borderRadius: 24, padding: 'clamp(16px, 3vw, 28px)', margin: 'calc(-1 * clamp(0px, 1vw, 8px))' }}>
      <header className="stack" style={{ gap: 8 }}>
        <Link href={e ? `/escrow/${e.id}` : '/escrow'} className="label" style={{ textDecoration: 'none', color: '#a9a69e' }}>← {i.escrow_reference}</Link>
        <div className="label" style={{ color: '#a9a69e' }}>{refund ? 'Refund approval' : 'Release approval'} · {i.escrow_reference}{e ? ` · ${e.title}` : ''}</div>
        <div className="row" style={{ gap: 8 }}>
          <span className="chip chip-ink" style={{ background: '#242424' }}>{words(i.status)}</span>
          <ClockChip clock={clock} />
          {i.release_part === 'held_back' ? <span className="chip">Held-back share</span> : null}
        </div>
        {clock?.clock_started_at ? <div style={{ fontSize: 14, opacity: 0.85 }}>Release clock: day {clock.working_days_running ?? 0} since the last condition closed {day(clock.clock_started_at)}. {stateLine}</div> : null}
      </header>

      <Ticket
        top={<>
          <div className="label">{verb}</div>
          <div className="money-sentence">{money(i.amount, i.currency)}</div>
          {i.holdback_amount && Number(i.holdback_amount) > 0 ? <div style={{ fontSize: 14 }}>Held back until its own condition closes: {money(i.holdback_amount, i.currency)}</div> : null}
        </>}
        bottom={<div style={{ fontSize: 16 }}>
          from escrow <span className="mono">{e?.virtual_account_ref || i.escrow_reference}</span> at {String((e?.payment_instructions as Record<string, unknown> | undefined)?.bank_name ?? 'the partner bank')} to <strong>{i.payee_name || 'the source account'}</strong>
          {payee.data ? <>, the {words(payee.data.kind).toLowerCase()}</> : null}{i.payee_account_last4 ? <>, account ending <span className="mono">{i.payee_account_last4}</span></> : null}
          {refund ? <>, where the deposit came from</> : null}.
          {i.subject_label ? <div className="muted" style={{ fontSize: 14, marginTop: 6 }}>For: {i.subject_label}</div> : null}
          {i.to_currency ? <div className="muted" style={{ fontSize: 14 }}>Converted to {i.to_currency} at the quote the client accepted.</div> : null}
          {payee.data && payee.data.name_match !== 'matched' ? <div style={{ marginTop: 8 }}><span className="name-mismatch">Bank name check: not matched</span></div> : null}
        </div>} />

      <section className="stack" aria-label="Gates" style={{ gap: 0 }}>
        <div className="label" style={{ color: '#a9a69e', marginBottom: 4 }}>Gates · all must pass</div>
        <Gate ok={!!i.client_approved_at || i.client_approval_method === 'standing' || refund} title={refund ? 'Refund prepared from the bank-confirmed deposit' : i.client_approved_at ? `Client approved on ${dayTime(i.client_approved_at)}` : i.client_approval_method === 'standing' ? 'Covered by the client\'s standing approval' : 'Client has not approved yet'} rule="RUL-11" />
        {rows.filter((g) => g.key !== 'client').map((g) => <Gate key={g.key} ok={g.ok} title={g.title} rule={g.rule} detail={g.reasons.map((r) => r.message).join(' ')} />)}
      </section>

      {i.last_send_error ? <Blocked title="The bank did not take the instruction">{i.last_send_error}</Blocked> : null}
      {failing.length && ['awaiting_client', 'pending_approval', 'approved'].includes(i.status) ? (
        <Blocked title={`${refund ? 'Refund' : 'Release'} blocked`}>{failing.flatMap((g) => g.reasons.map((r) => r.message)).slice(0, 3).join(' ') || failing[0].title}</Blocked>
      ) : null}
      {i.status === 'awaiting_client' ? <div className="strip-ink" style={{ background: '#1a1a1a' }}>Waiting for the client. Staff approvals open after the client approves.</div> : null}

      <div className="grid2">{slot(0)}{slot(1)}</div>

      <div style={{ fontSize: 14, opacity: 0.85 }}>
        After approval: the instruction is signed by both approvers and sent to the bank the same working day. No waiting period (RUL-33). The bank pays within the agreed time [TO VERIFY]. The status changes to Release approved, then Released when the bank confirms.
      </div>
      {i.status === 'sent' || i.status === 'confirmed' ? (
        <div className="stack" style={{ gap: 4, fontSize: 14 }}>
          <div>Sent {dayTime(i.sent_at)} by {i.sent_channel || 'the agreed channel'}{i.sent_reference ? `, ref ${i.sent_reference}` : ''}.</div>
          {i.document_sha256 ? <div className="mono" style={{ overflowWrap: 'anywhere', fontSize: 12 }}>Instruction SHA-256 {i.document_sha256}</div> : null}
          {i.bank_confirmation_event ? <div>✓ The bank confirmed payment.</div> : null}
        </div>
      ) : null}

      {hasRole('CM', 'RV') ? (
        <div className="row">
          {i.status === 'approved' && i.last_send_error ? <Button variant="primary" size="sm" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/release-instructions/${id}/send`).then(reload), 'Sent again.')}>Send again</Button> : null}
          {i.status === 'sent' && e ? (
            <ActionForm label="Record the bank's confirmation" variant="primary" path={`/v1/escrows/${e.id}/bank-events`} upload={{ subject_type: 'escrow', subject_id: e.id, role: 'bank_confirmation' }} fields={[
              { name: 'bank_reference', label: "Bank's reference", required: true }, { name: 'proof_evidence_id', label: "The bank's confirmation", type: 'file', required: true },
            ]} body={(v) => ({ kind: refund ? 'refund_confirmed' : 'release_confirmed', amount: { amount: i.amount, currency: i.to_currency || i.currency }, bank_reference: v.bank_reference, proof_evidence_id: v.proof_evidence_id, instruction_id: i.id })}
              onDone={reload} submitLabel="Save" intro="A second person checks it before it counts." />
          ) : null}
          {i.status === 'sent' ? (
            <ActionForm label="Bank rejected it" path={`/v1/release-instructions/${id}/bank-rejection`} upload={e ? { subject_type: 'escrow', subject_id: e.id, role: 'bank_rejection' } : undefined} fields={[
              { name: 'reason', label: "Bank's reason", type: 'textarea', required: true }, { name: 'proof_evidence_id', label: "The bank's message", type: 'file', required: true },
              { name: 'source_cannot_receive', label: 'The source account can no longer receive money', type: 'checkbox' },
            ]} body={(v) => ({ reason: v.reason, proof_evidence_id: v.proof_evidence_id, source_cannot_receive: !!v.source_cannot_receive })} onDone={reload} submitLabel="Save" />
          ) : null}
          {['awaiting_client', 'pending_approval'].includes(i.status) ? <ActionForm label="Withdraw instruction" path={`/v1/release-instructions/${id}/withdraw`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={reload} submitLabel="Withdraw" /> : null}
        </div>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
