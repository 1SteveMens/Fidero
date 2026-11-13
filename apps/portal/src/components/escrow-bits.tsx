'use client';
import Link from 'next/link';
import { Blocked, Money, NeedsYou, When, useGet } from '@tenmina/web-ui';
import { list, money, words, type Any } from './kit';

export const ESCROW_SENTENCE: Record<string, string> = {
  proposed: 'Waiting for everyone to accept the escrow terms.',
  agreed: 'Agreed. Pay the price to the bank using its instructions.',
  funded: 'The bank holds the money. Conditions are being closed.',
  ready_to_release: 'Every condition is closed. Your approval is needed. Tenmina staff approve after you.',
  client_approved: 'You approved. Two Tenmina staff now check and approve.',
  release_approved: 'Approved. Tenmina told the bank to pay.',
  partly_released: 'Part paid. The rest stays at the bank.',
  released: 'The bank paid. This escrow is complete.',
  frozen: 'No money can move until the check or dispute is resolved.',
  cancel_requested: 'Cancellation requested. Two Tenmina staff decide.',
  cancelled: 'Cancelled. Any money goes back to the account it came from.',
  closed: 'Closed.',
};

export const RELEASE_SENTENCE: Record<string, string> = {
  awaiting_client: 'Waiting for your approval. Nothing is paid until you approve.',
  pending_approval: 'You approved. Waiting for two Tenmina staff.',
  approved: 'Approved by two staff. Being sent to the bank.',
  sent: 'Sent to the bank. Waiting for the bank to confirm payment.',
  confirmed: 'The bank confirmed the payment.',
  declined: 'You declined this payment.',
  withdrawn: 'Withdrawn by Tenmina.',
  rejected: 'Rejected.',
  bank_rejected: 'The bank could not pay it. Tenmina is fixing it.',
};

/** The client's step first, then two Tenmina approvers (5.4, RUL-11). Approver names shown when given. */
export function ApprovalChain({ ins }: { ins: Any }) {
  const approvals: Any[] = ins.approvals ?? [];
  const row = (done: boolean, label: React.ReactNode, mine?: boolean) => (
    <div className="check-row"><span className={`tick ${done ? 'done' : ''}`} style={!done && mine ? { background: 'var(--orange)' } : undefined} aria-hidden>{done ? '✓' : ''}</span><div>{label}</div><span /></div>
  );
  return (
    <div>
      {row(!!ins.client_approved_at, ins.client_approved_at ? <>You approved <When value={ins.client_approved_at} withTime />{ins.client_approval_method === 'totp_code' ? ' (code checked)' : ''}</> : <strong>Your approval</strong>, !ins.client_approved_at && ins.status === 'awaiting_client')}
      {[0, 1].map((i) => {
        const ap = approvals[i];
        return <div key={i}>{row(!!ap && ap.decision !== 'reject', ap ? <>{ap.approver || `Tenmina approver ${i + 1}`} {ap.decision === 'reject' ? 'rejected' : 'approved'} <When value={ap.at} withTime /></> : <span className="muted">Tenmina approver {i + 1}{ins.client_approved_at ? '' : ', after you'}</span>)}</div>;
      })}
    </div>
  );
}

export function FreezeBanner({ e }: { e: Any }) {
  if (!e.freezes?.length && e.status !== 'frozen') return null;
  return (
    <>
      {(e.freezes?.length ? e.freezes : [{ reason: '' }]).map((f: Any, i: number) => (
        <Blocked key={i}>{f.reason || 'A check or dispute is open.'} {f.frozen_at ? <>Since <When value={f.frozen_at} />.</> : null} No money can move until it is resolved.</Blocked>
      ))}
    </>
  );
}

/** Payee changes on this escrow: orange only when the client must decide (SCR-PTL-55). */
export function PayeeChanges({ escrowId }: { escrowId: string }) {
  const q = useGet<Any>('/v1/payee-changes');
  const rows = list(q.data).filter((c: Any) => c.escrow === escrowId);
  if (!rows.length) return null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {rows.map((c: Any) => c.status === 'checks_passed' ? (
        <NeedsYou key={c.id} title={`Payee change: ${c.account_name}, new account ending ${c.account_last4}`} detail="Waiting for your decision." href={`/property/payee-changes/${c.id}`} />
      ) : (
        <Link key={c.id} href={`/property/payee-changes/${c.id}`} className="card-ink card-link">
          <div className="label" style={{ color: '#a9a69e' }}>Payee change · {words(c.status)}</div>
          <div>{c.account_name}, account ending {c.account_last4}</div>
          {c.cooling_off_until && new Date(c.cooling_off_until) > new Date() ? <div className="mono" style={{ fontSize: 13, color: '#a9a69e' }}>No money can go to the new account until <When value={c.cooling_off_until} withTime /></div> : null}
        </Link>
      ))}
    </div>
  );
}

export function FundsLine({ f }: { f: Any }) {
  return (
    <div className="stack" style={{ gap: 2 }}>
      <div style={{ fontSize: 28, fontWeight: 800 }}><Money value={money(f.held_at_bank, f.currency)} /></div>
      {Number(f.instructed_awaiting_bank) > 0 ? <div className="muted" style={{ fontSize: 14 }}><Money value={money(f.instructed_awaiting_bank, f.currency)} /> instructed, waiting for the bank to pay</div> : null}
      {f.last_bank_event_at ? <div className="mono muted" style={{ fontSize: 12 }}>Last bank confirmation <When value={String(f.last_bank_event_at).replace(' ', 'T')} withTime /></div> : null}
    </div>
  );
}
