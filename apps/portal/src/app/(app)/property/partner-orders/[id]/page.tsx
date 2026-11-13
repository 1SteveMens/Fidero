'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Button, KV, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { PageHead, useAction, words, type Any } from '@/components/kit';

/** J-06: a partner (for example a bank checking collateral) asked Tenmina to check a plot; the client confirms or declines. */
export default function PartnerOrder() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/partner-orders/${id}`);
  const a = useAction();
  if (q.isLoading) return <Skeleton lines={5} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const o = q.data;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${o.reference} · ${words(o.status)}`} title={`${o.partner} asked for a check`} />
      <KV items={[['Partner reference', o.partner_reference], ['Place', [o.locality, o.plot_number && `plot ${o.plot_number}`].filter(Boolean).join(', ')], ['Site plan', o.site_plan_ref], ['Seller', o.seller_name], ['Depth', words(o.tier)], ['Asked', <When key="c" value={o.created_at} />]]} />
      {o.status === 'awaiting_client' ? (
        <>
          <p style={{ margin: 0 }}>Nothing starts unless you confirm. If you confirm, the partner sees the status of the check. It sees the full report only if you agree to that separately in Sharing.</p>
          <Button variant="primary" busy={a.busy === 'c'} onClick={() => a.run('c', () => a.post(`/v1/partner-orders/${id}/confirm`), 'Confirmed', () => q.mutate())}>Confirm the check</Button>
          <Button variant="ghost" busy={a.busy === 'd'} onClick={() => a.run('d', () => a.post(`/v1/partner-orders/${id}/decline`), 'Declined', () => q.mutate())}>Decline</Button>
        </>
      ) : null}
      {o.order_id ? <Link className="btn btn-dark" href={`/property/orders/${o.order_id}`}>Open the order</Link> : null}
      {o.case_id ? <Link className="btn btn-dark" href={`/property/cases/${o.case_id}`}>Open the case</Link> : null}
      <Link className="btn btn-ghost" href="/property/sharing">Sharing and consent</Link>
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}
