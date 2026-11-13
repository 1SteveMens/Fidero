'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, Button, Chip, KV, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { ApproveMoney, EvidenceLink, Ink, PageHead, Proof, RadioCard, Section, money, useAction, words, type Any } from '@/components/kit';

/** W-27 · SCR-PTL-40: pay a bill, by either route. Client-direct: the client pays the verified account and tells us.
 * Held funds: the bank pays from money it holds, after the client's approval and two Tenmina staff. */
export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/invoices/${id}`);
  const inv = q.data;
  const pv = useGet<Any>(inv && inv.status === 'checked' ? `/v1/invoices/${id}/approval-preview` : null, undefined, { shouldRetryOnError: false });
  const a = useAction();
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!inv) return <Ink><ProblemBox error={q.error} /></Ink>;
  const p = pv.data;
  const canApprove = inv.status === 'checked' && inv.check_status === 'checked';
  const refresh = () => { q.mutate(); pv.mutate(); };
  const held = p?.held_funds;
  const short = inv.route === 'held_funds' && (!held || Number(held.available_to_instruct?.amount ?? 0) < Number(inv.amount.amount));
  return (
    <Ink>
      <PageHead back={{ href: inv.family_member ? `/family/members/${inv.family_member.id}` : '/family', label: inv.family_member?.full_name ?? 'Family' }} label={`${inv.institution.name}${inv.family_member ? ` · ${words(inv.family_member.relationship)}` : ''}`} title={inv.description || 'Bill'} sub={inv.status_text} />
      <div className="row">{inv.institution.status === 'verified' ? <Proof>Institution verified</Proof> : <Chip>Institution {words(inv.institution.status)}</Chip>}<Chip>{inv.submitted_by === 'institution' ? 'Sent by the institution' : 'Uploaded by you'}</Chip></div>
      <section className="card">
        <KV items={[
          ['Bill number', <span key="r" className="mono">{inv.institution_reference}</span>],
          ['Amount', <Money key="a" value={inv.amount} />],
          ['Due', inv.due_on ? <When key="d" value={inv.due_on} /> : '—'],
          ['Name on the bill', inv.name_on_invoice || '—'],
          ['File', inv.evidence ? <EvidenceLink key="e" id={inv.evidence} label="Open the bill" /> : '—'],
        ]} />
      </section>
      <Section title="Checks">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          <div className="check-row"><span className={`tick ${inv.contact_confirmed ? 'done' : ''}`}>{inv.contact_confirmed ? '✓' : ''}</span><div>{inv.contact_confirmed ? <>Confirmed with the institution on <When value={inv.contact_confirmed.at} /></> : 'Confirm the bill with the institution'}</div><span /></div>
          <div className="check-row"><span className={`tick ${inv.institution.status === 'verified' ? 'done' : ''}`}>{inv.institution.status === 'verified' ? '✓' : ''}</span><div>The institution and its account are verified</div><span /></div>
          <div className="check-row"><span className={`tick ${inv.check_status === 'checked' ? 'done' : ''}`}>{inv.check_status === 'checked' ? '✓' : ''}</span><div>{inv.check_status === 'checked' ? `Checked by ${inv.checked_by_name ?? 'Tenmina'}` : `Bill check: ${words(inv.check_status)}`}{inv.check_note ? <div className="muted" style={{ fontSize: 13 }}>{inv.check_note}</div> : null}</div><span /></div>
          {(inv.check_flags ?? []).map((f: Any, i: number) => <div key={i} className="check-row"><span className="tick">✕</span><div>{f.message ?? String(f)}</div><span /></div>)}
        </div>
      </Section>
      {inv.status === 'checked' ? (
        <Section title="How to pay">
          <RadioCard name="route" checked={inv.route === 'client_direct'} onChange={() => a.run('route', () => a.post(`/v1/invoices/${id}/route`, { route: 'client_direct' }), undefined, refresh)}>
            <strong>I pay the institution myself</strong><div className="muted" style={{ fontSize: 14 }}>We show you its verified account. You pay from your bank and tell us. The institution confirms it.</div>
          </RadioCard>
          <RadioCard name="route" checked={inv.route === 'held_funds'} onChange={() => a.run('route', () => a.post(`/v1/invoices/${id}/route`, { route: 'held_funds' }), undefined, refresh)}>
            <strong>The bank pays from money it holds for me</strong><div className="muted" style={{ fontSize: 14 }}>After you approve, two Tenmina staff approve, then the bank pays the institution.</div>
          </RadioCard>
          {short ? <Blocked title="Not enough held at the bank">{held ? <>Add money to your held amount first. <Link href={`/property/escrows/${held.escrow_id}/pay-in`} style={{ color: '#a3ee5b' }}>Add money</Link></> : <>You have no money held at the bank yet. <Link href="/family/held-funds" style={{ color: '#a3ee5b' }}>Set it up</Link></>}</Blocked> : null}
        </Section>
      ) : null}
      {canApprove && p ? (
        <ApproveMoney
          amount={inv.amount}
          payee={p.institution.account_name}
          payeeLines={<>
            <div className="mono" style={{ fontSize: 14 }}>Account ending {p.institution.account_last4}</div>
            {p.institution.name_match === 'matched' ? <span className="proof" style={{ alignSelf: 'flex-start' }}>✓ The bank confirmed the account name</span> : <span className="unmatched" style={{ alignSelf: 'flex-start' }}>The bank did not match the account name</span>}
          </>}
          above={<div style={{ color: '#6a675f', fontSize: 14 }}>{inv.route === 'held_funds' ? `From the money held at the bank${held?.escrow_reference ? `, ${held.escrow_reference}` : ''}` : 'You pay it yourself, after approving'}</div>}
          disabled={!!short || p.institution.name_match !== 'matched'}
          onApprove={(code) => a.post(`/v1/invoices/${id}/client-approval`, { confirm_amount: inv.amount, confirm_payee_account_name: p.institution.account_name, code }).then(() => { refresh(); a.show('Approved.'); })}
          onDecline={(reason) => a.post(`/v1/invoices/${id}/client-decline`, { reason }).then(() => { refresh(); a.show('Declined. Nothing is paid.'); })}
          declineLabel="Question this bill"
          note={<p className="muted" style={{ margin: 0, fontSize: 14 }}>Your approval alone pays nothing{inv.route === 'held_funds' ? '. Two Tenmina staff approve next, then the bank pays the institution.' : '. Next we show you the account to pay.'}</p>}
        />
      ) : null}
      {inv.client_approved_at ? <p style={{ margin: 0 }}>You approved <Money value={inv.amount} /> on <When value={inv.client_approved_at} withTime />.</p> : null}
      {inv.payment ? <Link href={`/family/fee-payments/${inv.payment.id}`} className="btn btn-primary">{inv.payment.status === 'awaiting_client_payment' ? 'See where to pay' : 'Follow the payment'}</Link> : null}
      {inv.service_order ? (
        <section className="card spread">
          <span>Tenmina&apos;s charge for checking this payment · <span className="mono">{inv.service_order.reference}</span></span>
          {inv.service_order.status === 'paid' ? <Proof>Paid</Proof> : <Link className="btn btn-ghost btn-sm" href={`/property/orders/${inv.service_order.id}`}>Pay the charge</Link>}
        </section>
      ) : null}
      {inv.status === 'rejected' && inv.status_reason ? <Blocked title="Rejected">{inv.status_reason}</Blocked> : null}
      <ProblemBox error={a.error} />
      {['submitted', 'draft', 'checked'].includes(inv.status) ? <Button variant="ghost" busy={a.busy === 'x'} onClick={() => a.run('x', () => a.post(`/v1/invoices/${id}/cancellation`, { reason: 'Cancelled by the client' }), 'Cancelled', refresh)}>Cancel this bill</Button> : null}
      {a.toast}
    </Ink>
  );
}
