'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, Money, ProblemBox, Skeleton, Steps, When, useGet } from '@tenmina/web-ui';
import { Copy, EvidenceLink, FilePick, Ink, PageHead, Proof, fileFields, useAction, words, type Any } from '@/components/kit';
import { RELEASE_SENTENCE } from '@/components/escrow-bits';

/** A family payment after approval. Client-direct: the verified account to pay, then "I have paid". */
export default function FeePayment() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/fee-payments/${id}`);
  const a = useAction();
  const [f, setF] = useState({ paid_on: new Date().toISOString().slice(0, 10), reference: '' });
  const [file, setFile] = useState<File | null>(null);
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const p = q.data;
  const pt = p.pay_to;
  const direct = p.route === 'client_direct';
  const s = p.status;
  const order = direct ? ['awaiting_client_payment', 'client_reported', 'paid', 'receipted'] : ['instructed', 'paid', 'receipted'];
  const at = Math.max(0, order.indexOf(s === 'receipt_overdue' ? 'paid' : s));
  return (
    <Ink>
      <PageHead back={{ href: `/family/invoices/${p.invoice.id}`, label: 'The bill' }} label={`${p.invoice.institution} · ${p.invoice.reference}`} title={s === 'awaiting_client_payment' ? 'Pay the institution' : words(s)} />
      <div style={{ fontSize: 32, fontWeight: 800 }}><Money value={p.amount} /></div>
      <Steps items={(direct ? ['You pay the institution', 'You tell us', 'The institution confirms', 'Receipt'] : ['The bank is told to pay', 'The bank pays', 'Receipt']).map((label, i) => ({ label, state: i < at || s === 'receipted' ? 'done' : i === at ? 'now' : 'next' }))} />
      {s === 'awaiting_client_payment' && pt ? (
        <>
          <section className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            {[['Account name', pt.account_name], ['Bank', pt.bank_name], ['Account number', pt.account_number], ['Reference', pt.reference]].map(([k, v]) => (
              <div key={k} className="check-row" style={{ gridTemplateColumns: '1fr auto' }}><div><div className="label">{k}</div><div className="mono" style={{ fontSize: 17, overflowWrap: 'anywhere' }}>{v}</div></div>{k !== 'Bank' ? <Copy value={String(v)} /> : <span />}</div>
            ))}
          </section>
          <p style={{ margin: 0 }}>{pt.note}</p>
          <form className="card stack" onSubmit={async (e) => { e.preventDefault(); a.run('paid', async () => a.post(`/v1/fee-payments/${id}/client-payment`, { ...f, ...(file ? await fileFields(file) : {}) }), 'Thank you. We will ask the institution to confirm.', () => q.mutate()); }}>
            <h3 style={{ margin: 0 }}>I have paid</h3>
            <Field label="Date you paid"><Input type="date" value={f.paid_on} onChange={(e) => setF({ ...f, paid_on: e.target.value })} /></Field>
            <Field label="Your bank's transfer reference"><Input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
            <FilePick label={file ? `Proof: ${file.name}` : 'Add proof of transfer (optional)'} onFile={setFile} />
            <Button variant="action" type="submit" busy={a.busy === 'paid'}>Tell Tenmina I have paid</Button>
          </form>
        </>
      ) : null}
      {p.release_status ? <p style={{ margin: 0 }}>{RELEASE_SENTENCE[p.release_status] ?? words(p.release_status)}</p> : null}
      {p.release_instruction ? <Link className="btn btn-ghost" href={`/property/releases/${p.release_instruction}`}>The bank instruction</Link> : null}
      {p.client_reported_at ? <p className="muted" style={{ margin: 0 }}>You told us you paid on <When value={p.client_paid_on} /> (reference {p.client_transfer_reference || '—'}).</p> : null}
      {p.institution_confirmed_at ? <Proof>The institution confirmed it received the money <When value={p.institution_confirmed_at} /></Proof> : null}
      {p.paid_at ? <Proof>Paid <When value={p.paid_at} />{p.bank_reference ? ` · bank reference ${p.bank_reference}` : ''}</Proof> : null}
      {s === 'receipt_overdue' ? <p>The institution&apos;s receipt is late. We are chasing it.</p> : null}
      <div className="row">{p.receipt_evidence ? <EvidenceLink id={p.receipt_evidence} label="Receipt" /> : null}{p.confirmation_evidence ? <EvidenceLink id={p.confirmation_evidence} label="Confirmation" /> : null}</div>
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
