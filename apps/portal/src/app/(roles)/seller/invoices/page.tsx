'use client';
/* Seller invoices for listing and success fees (US-PAY-007). Paid to Tenmina through the payment
   provider: these are Tenmina's own fees, never purchase money (RUL-01). */
import { useState } from 'react';
import { Button, Card, Chip, Field, Money, ProblemBox, Select, Status, When, useGet } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { EmptyText, Loaded, PageHead, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { goToCheckout, type PaymentStarted } from '@/components/roles/pay';

type Invoice = { id: string; number: string; kind: string; description: string; amount: MoneyT; status: string; issued_at: string | null; due_on: string | null; paid_at: string | null; void_reason: string };

export default function SellerInvoices() {
  const q = useGet<Page<Invoice>>('/v1/seller-invoices');
  return (
    <div className="stack">
      <PageHead label="Selling" title="Invoices">Tenmina&apos;s fees for checking and listing your plots. The fee is the same whatever the verdict.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((i) => <InvoiceCard key={i.id} i={i} />) : <EmptyText>No invoices yet.</EmptyText>}</Loaded>
    </div>
  );
}

function InvoiceCard({ i }: { i: Invoice }) {
  const api = useApi();
  const act = useAct();
  const [method, setMethod] = useState('card');
  const due = i.status === 'issued';
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label">{i.number} · {words(i.kind)}</div><strong>{i.description}</strong></div><Money value={i.amount} /></div>
      <div className="row" style={{ fontSize: 14 }}>
        {i.status === 'paid' ? <Chip tone="lime">✓ Paid</Chip> : <Status value={i.status} needsYou={due} />}
        {i.paid_at ? <span className="muted">Paid <When value={i.paid_at} /></span> : i.due_on ? <span className="muted">Due <When value={i.due_on} /></span> : null}
      </div>
      {i.void_reason ? <span className="muted">{i.void_reason}</span> : null}
      {due ? (
        <div className="row">
          <Field label="Pay by"><Select value={method} onChange={(e) => setMethod(e.target.value)}><option value="card">Card</option><option value="mobile_money">Mobile money</option></Select></Field>
          <Button variant="action" busy={act.busy === 'pay'} onClick={() => act.run('pay', async () => {
            const p = await api<PaymentStarted>('POST', `/v1/seller-invoices/${i.id}/payments`, { method, return_url: '/seller/invoices' });
            goToCheckout(p, '/seller/invoices');
          })}>Pay Tenmina&apos;s fee</Button>
        </div>
      ) : null}
      <ProblemBox error={act.error} />
    </Card>
  );
}
