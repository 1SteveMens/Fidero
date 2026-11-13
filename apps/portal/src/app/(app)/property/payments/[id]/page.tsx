'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect } from 'react';
import { Button, KV, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, useAction, words, type Any } from '@/components/kit';

const OUTCOME: Record<string, string> = { success: 'Pay', decline: 'Card declined', insufficient_funds: 'Not enough money', timeout: 'No answer', cancel: 'Cancel', cancelled: 'Cancel' };

/** SCR-PTL-10 checkout (the fake provider in development) and SCR-PTL-11, the payment result and receipt. */
export default function PaymentPage() {
  const { id } = useParams<{ id: string }>();
  const p = useGet<Any>(`/v1/payments/${id}`);
  const pay = p.data;
  const checkout = useGet<Any>(pay?.status === 'initiated' ? `/v1/payments/${id}/fake-checkout` : null, undefined, { shouldRetryOnError: false });
  const receipt = useGet<Any>(pay?.status === 'success' ? `/v1/payments/${id}/receipt` : null, undefined, { shouldRetryOnError: false });
  const a = useAction();
  useEffect(() => {
    if (pay && ['pending', 'processing'].includes(pay.status)) { const t = setTimeout(() => a.post(`/v1/payments/${id}/refresh`).then(() => p.mutate()).catch(() => undefined), 2500); return () => clearTimeout(t); }
  }, [pay?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (p.isLoading) return <Skeleton lines={5} />;
  if (!pay) return <ProblemBox error={p.error} />;
  const back = pay.order ? `/property/orders/${pay.order}` : '/property';
  return (
    <Ink>
      <PageHead back={{ href: back, label: pay.order_reference ?? 'Back' }} label="Tenmina's fee" title={pay.status === 'success' ? 'Payment received' : pay.status === 'failed' ? 'The payment did not go through' : 'Pay the fee'} />
      <div style={{ fontSize: 36, fontWeight: 800 }}><Money value={pay.amount} /></div>
      {pay.status === 'initiated' && checkout.data ? (
        <section className="card stack">
          <div className="label">{checkout.data.merchant} · {words(checkout.data.method)}</div>
          <p className="muted" style={{ margin: 0 }}>{checkout.data.note}</p>
          <div className="stack" style={{ gap: 8 }}>
            {(checkout.data.outcomes as string[]).sort((x) => (x === 'success' ? -1 : 1)).map((o) => (
              <Button key={o} variant={o === 'success' ? 'primary' : 'ghost'} busy={a.busy === o} onClick={() => a.run(o, () => a.post(`/v1/payments/${id}/fake-checkout`, { outcome: o }), undefined, () => p.mutate())}>{OUTCOME[o] ?? words(o)}</Button>
            ))}
          </div>
        </section>
      ) : null}
      {pay.status === 'pending' || pay.status === 'processing' ? <p>Waiting for the payment provider to confirm. This page updates by itself.</p> : null}
      {pay.status === 'failed' ? (
        <section className="card stack">
          <p style={{ margin: 0 }}>{pay.failure_message || 'The provider refused the payment.'} Nothing was taken.</p>
          {pay.order ? <Link className="btn btn-primary" href={back}>Try again</Link> : null}
        </section>
      ) : null}
      {pay.status === 'success' ? (
        <section className="card stack">
          <Proof>Paid <When value={pay.confirmed_at} withTime /></Proof>
          {receipt.data?.receipt ? (
            <KV items={[
              ['Receipt', <span key="n" className="mono">{receipt.data.receipt.number}</span>],
              ['For', receipt.data.receipt.description],
              ['Paid by', receipt.data.receipt.issued_to_name],
              ['Method', receipt.data.receipt.method_detail || words(receipt.data.receipt.method)],
              ['Issued', <When key="i" value={receipt.data.receipt.issued_at} withTime />],
              ['Fingerprint', <span key="h" className="mono" style={{ fontSize: 12 }}>{receipt.data.receipt.sha256}</span>],
            ]} />
          ) : <Skeleton lines={2} />}
          {(receipt.data?.credit_notes ?? []).map((c: Any) => <div key={c.id} className="spread"><span>Credit note <span className="mono">{c.number}</span></span><Money value={c.amount} /></div>)}
          <p className="muted" style={{ margin: 0 }}>What happens next: a case manager starts your check. We tell you at every step.</p>
          {pay.order ? <Link className="btn btn-primary" href={back}>Open my order</Link> : null}
        </section>
      ) : null}
      <ProblemBox error={a.error} />
    </Ink>
  );
}
