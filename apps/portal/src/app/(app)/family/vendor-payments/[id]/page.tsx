'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, KV, Money, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { ApproveMoney, EvidenceLink, Ink, PageHead, Proof, Section, useAction, words, type Any } from '@/components/kit';

/** An event vendor payment: evidence first, then the client's approval on black, then two Tenmina staff (RUL-11, RUL-22). */
export default function VendorPayment() {
  const { id } = useParams<{ id: string }>();
  const { stepUp } = useSession();
  const q = useGet<Any>(`/v1/vendor-payments/${id}`);
  const ev = useGet<Any>(q.data ? `/v1/events/${q.data.event}` : null);
  const a = useAction();
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const p = q.data;
  const vendor = (ev.data?.vendors ?? []).find((v: Any) => v.id === p.vendor);
  const mine = p.status === 'evidenced';
  return (
    <Ink>
      <PageHead back={{ href: `/family/events/${p.event}`, label: ev.data?.name ?? 'The event' }} label={`${words(p.kind)} · ${words(p.status)}`} title={mine ? 'Approve this payment' : p.description || 'Vendor payment'} />
      {(p.missing ?? []).length ? <Blocked title="Waiting for proof">{p.missing.map((m: Any) => m.message ?? String(m)).join(' ')}</Blocked> : null}
      <Section title="Proof">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          <div className="check-row"><span className={`tick ${p.quote_evidence ? 'done' : ''}`}>{p.quote_evidence ? '✓' : ''}</span><div>Quote</div>{p.quote_evidence ? <EvidenceLink id={p.quote_evidence} label="Open" variant="preview" /> : <span />}</div>
          <div className="check-row"><span className={`tick ${p.invoice_evidence ? 'done' : ''}`}>{p.invoice_evidence ? '✓' : ''}</span><div>Invoice</div>{p.invoice_evidence ? <EvidenceLink id={p.invoice_evidence} label="Open" variant="preview" /> : <span />}</div>
          <div className="check-row"><span className={`tick ${p.delivery_evidence_ids?.length ? 'done' : ''}`}>{p.delivery_evidence_ids?.length ? '✓' : ''}</span><div>Delivery proof ({p.delivery_evidence_ids?.length ?? 0})</div><span /></div>
          <div className="check-row"><span className={`tick ${p.family_confirmed_at ? 'done' : ''}`}>{p.family_confirmed_at ? '✓' : ''}</span><div>{p.family_confirmed_at ? <>Family confirmed <When value={p.family_confirmed_at} /></> : `Family confirmation: ${words(p.confirmation_status) || 'not needed yet'}`}</div><span /></div>
        </div>
      </Section>
      {mine ? (
        <ApproveMoney amount={p.amount} payee={vendor?.payee?.name ?? p.vendor_name}
          payeeLines={vendor?.payee ? <div className="mono" style={{ fontSize: 14 }}>Account ending {vendor.payee.account_last4} · {words(vendor.payee.status)}</div> : null}
          onApprove={async (code) => { await stepUp(code); await a.post(`/v1/vendor-payments/${id}/client-approval`, { confirm_amount: p.amount, acknowledge_budget_warning: true }); q.mutate(); a.show('Approved. Two Tenmina staff approve next.'); }}
          onDecline={(reason) => a.post(`/v1/vendor-payments/${id}/reject`, { reason }).then(() => { q.mutate(); a.show('Rejected. Nothing is paid.'); })}
          declineLabel="Reject this payment" />
      ) : (
        <section className="card">
          <KV items={[['Amount', <Money key="a" value={p.amount} />], ['To', p.vendor_name], ['You approved', p.client_approved_at ? <When key="c" value={p.client_approved_at} withTime /> : '—'], ['Paid', p.paid_at ? <When key="p" value={p.paid_at} withTime /> : '—'], ['Bank reference', p.bank_reference || '—']]} />
          {p.paid_at ? <Proof>The bank paid {p.vendor_name}</Proof> : null}
          {p.reject_reason ? <p>{p.reject_reason}</p> : null}
        </section>
      )}
      {p.release_instruction ? <Link className="btn btn-ghost" href={`/property/releases/${p.release_instruction}`}>The bank instruction</Link> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
