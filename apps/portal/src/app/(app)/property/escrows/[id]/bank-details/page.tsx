'use client';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Money, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { Copy, Ink, PageHead, words, type Any } from '@/components/kit';

function Row({ k, v, copy, note }: { k: string; v?: string | null; copy?: boolean; note?: string }) {
  if (!v) return null;
  return (
    <div className="check-row" style={{ gridTemplateColumns: '1fr auto' }}>
      <div><div className="label">{k}</div><div className="mono" style={{ fontSize: 17, overflowWrap: 'anywhere' }}>{v}</div>{note ? <div className="muted" style={{ fontSize: 13 }}>{note}</div> : null}</div>
      {copy ? <Copy value={v} /> : <span />}
    </div>
  );
}

/** W-10 · SCR-PTL-18: the bank's details for this escrow only. Never Tenmina's account (RUL-01, RUL-34). */
function Details() {
  const { id } = useParams<{ id: string }>();
  const quoteId = useSearchParams().get('quote');
  const e = useGet<Any>(`/v1/escrows/${id}`);
  const q = useGet<Any>(quoteId ? `/v1/fx-quotes/${quoteId}` : null);
  if (e.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!e.data) return <Ink><ProblemBox error={e.error} /></Ink>;
  const esc = e.data;
  const pi = esc.payment_instructions ?? {};
  const quote = q.data;
  const fx = quote ? (pi.foreign_currency_accounts ?? []).find((f: Any) => f.currency === quote.from_currency) : null;
  const partnerRoute = quote?.route === 'transfer_partner';
  return (
    <Ink>
      <PageHead back={{ href: `/property/escrows/${id}`, label: `Escrow ${esc.reference}` }} label="Bank payment instructions" title="Pay the bank" />
      <div className="card" style={{ display: 'flex', gap: 10 }}>
        <span aria-hidden style={{ fontSize: 22 }}>🛡</span>
        <div>These are the bank&apos;s details, not Tenmina&apos;s. Tenmina never asks you to pay land or family money to Tenmina.</div>
      </div>
      {esc.status === 'proposed' ? <p>The bank will open the escrow once everyone has accepted the terms.</p> : !pi.available ? <p>{pi.note || 'The partner bank is opening this escrow’s own account number. We will tell you when you can pay.'}</p> : (
        <section className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          <Row k="Bank" v={pi.bank_name} />
          {quote ? <Row k="Route" v={words(quote.route)} note="Chosen on the last page." /> : null}
          {partnerRoute ? (
            <div className="check-row" style={{ gridTemplateColumns: '1fr' }}><div>Use the transfer service you chose. Send to the escrow account below, with this escrow&apos;s reference. Never use a payment link someone sends you.</div></div>
          ) : null}
          <Row k="Account name" v={fx?.account_name || pi.account_name} copy />
          <Row k="Account number" v={fx?.account_number || fx?.virtual_account_ref || pi.account_number} copy note={fx ? `This escrow's own ${fx.currency} account` : undefined} />
          <Row k="SWIFT" v={fx?.swift || pi.swift} copy />
          <Row k="Reference" v={fx?.virtual_account_ref || pi.virtual_account_ref || pi.reference} copy note="Always use the reference. Without it the bank cannot match your payment." />
          {quote ? (
            <div className="check-row" style={{ gridTemplateColumns: '1fr' }}>
              <div><div className="label">Amount</div><div style={{ fontSize: 22, fontWeight: 800 }}><Money value={{ amount: quote.from_amount, currency: quote.from_currency }} /></div><div className="muted">gives <Money value={{ amount: quote.expected_to_amount, currency: quote.to_currency }} /> at your quote</div></div>
            </div>
          ) : null}
        </section>
      )}
      <p style={{ margin: 0 }}>If anyone sends you different details, do not pay. Call us first.</p>
      <p className="muted" style={{ margin: 0 }}>This account number is for this escrow only. {pi.bank_name ?? 'The partner bank'} holds the money as escrow agent, not Tenmina.</p>
      <div className="row">
        <Link href={`/property/escrows/${id}/pay-in`} className="btn btn-ghost">Change the route</Link>
        <button className="btn btn-ghost" onClick={() => window.print()}>Save as PDF</button>
        <Link href={esc.case_id ? `/property/cases/${esc.case_id}` : "/inbox"} className="btn btn-ghost">Report suspicious details</Link>
      </div>
    </Ink>
  );
}

export default function BankDetails() {
  return <Suspense><Details /></Suspense>;
}
