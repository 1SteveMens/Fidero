'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { ApproveMoney, Ink, PageHead, Proof, Section, money, useAction, words, type Any } from '@/components/kit';
import { ApprovalChain, RELEASE_SENTENCE } from '@/components/escrow-bits';

/** The client's release approval (W-09 "Your approval", 5.4): on black, the ticket, press and hold, then the code. */
export default function ReleaseApproval() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/release-instructions/${id}`);
  const esc = useGet<Any>(q.data ? `/v1/escrows/${q.data.escrow}` : null);
  const a = useAction();
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const ins = q.data;
  const e = esc.data;
  const f = e?.funds?.find((x: Any) => x.currency === ins.currency) ?? e?.funds?.[0];
  const blocked = (ins.blocking_reasons ?? []).length > 0;
  const mine = ins.status === 'awaiting_client';
  const approve = (code: string) => a.post(`/v1/release-instructions/${id}/client-approval`, { approve: true, code, gesture: 'press_and_hold' }).then(() => { q.mutate(); a.show('Approved. Two Tenmina staff now check and approve.'); });
  const decline = (reason: string) => a.post(`/v1/release-instructions/${id}/client-approval`, { approve: false, reason }).then(() => { q.mutate(); a.show('Declined. Nothing is paid.'); });
  return (
    <Ink>
      <PageHead back={{ href: `/property/escrows/${ins.escrow}`, label: `Escrow ${ins.escrow_reference}` }} label={`${words(ins.kind)} · ${words(ins.release_part)}`} title={mine ? 'Approve this payment' : RELEASE_SENTENCE[ins.status] ?? words(ins.status)} />
      {ins.subject_label ? <p style={{ margin: 0, fontSize: 17 }}>{ins.subject_label}</p> : null}
      {blocked ? (
        <Blocked title={mine ? 'You cannot approve yet' : 'Release blocked'}>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{ins.blocking_reasons.map((b: Any, i: number) => <li key={i}>{b.message}{b.rule ? <span className="mono"> ({b.rule})</span> : null}</li>)}</ul>
        </Blocked>
      ) : null}
      {mine ? (
        <ApproveMoney
          amount={ins.money}
          above={Number(ins.holdback_amount) > 0 ? <div className="muted" style={{ color: '#6a675f' }}>Held back for defects: <Money value={money(ins.holdback_amount, ins.currency)} /></div> : null}
          payee={ins.payee_name}
          payeeLines={<div className="mono" style={{ fontSize: 14 }}>Account ending {ins.payee_account_last4} · verified payee</div>}
          note={f ? <div className="card" style={{ fontSize: 14 }}>From {e?.payment_instructions?.bank_name ?? 'the partner bank'}, escrow {ins.escrow_reference}. Held now: <Money value={money(f.held_at_bank, f.currency)} />. Two Tenmina staff approve after you. No waiting period after the last approval.</div> : null}
          disabled={blocked}
          onApprove={approve}
          onDecline={decline}
          declineLabel="Do not pay this"
        />
      ) : (
        <section className="card stack">
          <div className="spread"><span>{ins.payee_name} · account ending {ins.payee_account_last4}</span><Money value={ins.money} /></div>
          {ins.sent_at ? <div className="mono muted" style={{ fontSize: 13 }}>Sent to the bank <When value={ins.sent_at} withTime /></div> : null}
          {ins.clock?.bank_pay_due_on ? <div className="mono muted" style={{ fontSize: 13 }}>Expected paid by <When value={ins.clock.bank_pay_due_on} /></div> : null}
          {ins.status === 'confirmed' ? <Proof>The bank confirmed the payment</Proof> : null}
        </section>
      )}
      <Section title="Approvals">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}><ApprovalChain ins={ins} /></div>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>You approve first. Then two different Tenmina staff approve. Silence is never approval: if you do nothing, nothing is paid.</p>
      </Section>
      <ProblemBox error={a.error} />
      {ins.document_sha256 ? <div className="mono muted" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>Instruction fingerprint {ins.document_sha256}</div> : null}
      <Link href={`/property/escrows/${ins.escrow}`} className="btn btn-ghost">Open the escrow</Link>
      {a.toast}
    </Ink>
  );
}
