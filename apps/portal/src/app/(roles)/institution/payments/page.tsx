'use client';
/* Payments to the institution (FR-FEE-003, FR-FEE-004): confirm money received when the family paid you
   directly, and upload your receipt for every payment. */
import { useState } from 'react';
import { Button, Chip, ProblemBox, When, Money, useGet } from '@tenmina/web-ui';
import { EmptyText, EvidenceLink, FilePick, Loaded, PageHead, PayeeLine, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { toBase64 } from '@/components/roles/files';
import type { FeePayment, Institution } from '@/components/roles/fees';

export default function InstitutionPayments() {
  const inst = useGet<Page<Institution>>('/v1/institutions');
  const q = useGet<Page<FeePayment>>('/v1/fee-payments');
  const i = items(inst.data)[0];
  return (
    <div className="stack">
      <PageHead label="Institution" title="Payments">Money paid to your account for families abroad. Please upload a receipt for each.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((p) => <PaymentCard key={p.id} p={p} inst={i} onDone={() => q.mutate()} />) : <EmptyText>No payments yet.</EmptyText>}</Loaded>
    </div>
  );
}

function PaymentCard({ p, inst, onDone }: { p: FeePayment; inst?: Institution; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const direct = p.route === 'client_direct';
  const needsConfirm = direct && p.status === 'client_reported' && !p.institution_confirmed_at;
  const needsReceipt = (p.status === 'paid' || p.status === 'receipt_overdue') && !p.receipt_received_at;
  return (
    <div className="card-ink stack">
      <div className="spread"><span><span className="mono">{p.invoice.reference}</span></span><strong style={{ fontSize: 20 }}><Money value={p.amount} /></strong></div>
      {inst?.payee ? <PayeeLine planned={!p.paid_at} name={inst.payee.account_name} last4={inst.payee.account_last4} bank={inst.payee.bank_name} /> : null}
      <div className="row">{p.paid_at ? <Chip tone="lime">✓ Paid <When value={p.paid_at} /></Chip> : <Chip>{words(p.status)}</Chip>}{p.bank_reference ? <span className="mono" style={{ fontSize: 12 }}>{p.bank_reference}</span> : null}</div>
      <span className="muted" style={{ fontSize: 14 }}>{direct ? 'The family pays you directly from their bank.' : 'The partner bank pays you from money it holds for the family.'}</span>
      {needsConfirm ? (
        <>
          <span>The family says they paid on {p.client_paid_on ? <When value={p.client_paid_on} /> : 'a recent date'}{p.client_transfer_reference ? <>, reference <span className="mono">{p.client_transfer_reference}</span></> : null}. Check your account.</span>
          <div className="row">
            <Button variant="action" busy={act.busy === 'y'} onClick={() => act.run('y', async () => { await api('POST', `/v1/fee-payments/${p.id}/institution-confirmation`, { received: true, amount: p.amount, method: '' }); onDone(); }, 'Confirmed.')}>We received it</Button>
            <Button variant="ghost" style={{ color: '#fff' }} busy={act.busy === 'n'} onClick={() => act.run('n', async () => { await api('POST', `/v1/fee-payments/${p.id}/institution-confirmation`, { received: false, method: '' }); onDone(); }, 'Recorded. Tenmina will follow up.')}>Not received</Button>
          </div>
        </>
      ) : null}
      {p.receipt_received_at ? <div className="row"><span>Receipt received <When value={p.receipt_received_at} /></span><EvidenceLink id={p.receipt_evidence} label="Receipt" /></div> : null}
      {needsReceipt ? (
        <>
          {p.receipt_due_at ? <span>Receipt due by <When value={p.receipt_due_at} />.</span> : null}
          <FilePick label="Your receipt" file={file} onFile={setFile} accept="application/pdf,image/*" />
          <Button variant="action" disabled={!file} busy={act.busy === 'r'} onClick={() => act.run('r', async () => {
            await api('POST', `/v1/fee-payments/${p.id}/receipts`, { document_base64: await toBase64(file!), content_type: file!.type || 'application/pdf', file_name: file!.name });
            setFile(null); onDone();
          }, 'Receipt uploaded. The family can see it.')}>Upload receipt</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
