'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, KV, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { ApproveMoney, Copy, FilePick, Ink, PageHead, Proof, uploadEvidence, useAction, words, type Any } from '@/components/kit';

/** A project payment by either route: escrow (the bank pays) or client-direct (the client pays the verified payee). */
export default function ProjectPayment() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/project-payments/${id}`);
  const a = useAction();
  const [ref, setRef] = useState('');
  const [file, setFile] = useState<File | null>(null);
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const p = q.data;
  const pt = p.pay_to;
  const refresh = () => q.mutate();
  return (
    <Ink>
      <PageHead back={{ href: `/projects/${p.project_id}`, label: 'The project' }} label={`${p.route === 'escrow' ? 'Paid by the bank' : 'Paid by you'} · ${words(p.status)}`} title={p.label} />
      {p.status === 'awaiting_client' ? (
        <ApproveMoney amount={p.amount} payee={p.payee?.account_name} payeeLines={<div className="mono" style={{ fontSize: 14 }}>{p.payee?.bank_name} · account ending {p.payee?.account_last4}</div>}
          onApprove={(code) => a.post(`/v1/project-payments/${id}/client-approval`, { confirm_amount: p.reprice?.changed ? p.reprice.amount : undefined, code }).then(() => { refresh(); a.show('Approved.'); })}
          onDecline={(reason) => a.post(`/v1/project-payments/${id}/client-decline`, { reason }).then(() => { refresh(); a.show('Declined.'); })} />
      ) : (
        <section className="card">
          <KV items={[['Amount', <Money key="a" value={p.amount} />], ['To', `${p.payee?.account_name} · account ending ${p.payee?.account_last4}`], ['You approved', p.client_approved_at ? <When key="c" value={p.client_approved_at} withTime /> : '—'], ['Tenmina approved', p.release_approved_at ? <When key="r" value={p.release_approved_at} withTime /> : '—'], ['Paid', p.paid_at ? <When key="p" value={p.paid_at} withTime /> : '—']]} />
        </section>
      )}
      {pt && !p.client_paid_at && p.route === 'client_direct' && p.release_approved_at ? (
        <>
          <section className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            {Object.entries({ 'Account name': pt.account_name, Bank: pt.bank_name, 'Account number': pt.account_number, Reference: pt.reference }).filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="check-row" style={{ gridTemplateColumns: '1fr auto' }}><div><div className="label">{k}</div><div className="mono">{String(v)}</div></div>{k !== 'Bank' ? <Copy value={String(v)} /> : <span />}</div>
            ))}
          </section>
          {pt.note ? <p style={{ margin: 0 }}>{pt.note}</p> : null}
          <form className="card stack" onSubmit={async (e) => { e.preventDefault(); a.run('p', async () => { const ev = file ? await uploadEvidence(a.client, file, { type: 'bld_payment', id, role: 'client_payment_proof' }) : null; return a.post(`/v1/project-payments/${id}/client-payments`, { reference: ref, evidence_id: ev?.id ?? null }); }, 'Thank you', refresh); }}>
            <h3 style={{ margin: 0 }}>I have paid</h3>
            <Field label="Transfer reference"><Input value={ref} onChange={(e) => setRef(e.target.value)} required /></Field>
            <FilePick label={file ? `Proof: ${file.name}` : 'Add proof (optional)'} onFile={setFile} />
            <Button variant="action" type="submit" busy={!!a.busy}>Tell Tenmina I have paid</Button>
          </form>
        </>
      ) : null}
      {p.client_paid_at ? <p className="muted" style={{ margin: 0 }}>You reported paying on <When value={p.client_paid_at} /> (reference {p.client_paid_reference}).</p> : null}
      {p.paid_at ? <Proof>Paid <When value={p.paid_at} />{p.bank_reference ? ` · bank reference ${p.bank_reference}` : ''}</Proof> : null}
      {p.instruction_id ? <Link className="btn btn-ghost" href={`/property/releases/${p.instruction_id}`}>The bank instruction</Link> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
