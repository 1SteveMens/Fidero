'use client';
/* The development payment provider's hosted page (fake provider only). A real provider hosts card and
   mobile money entry on its own site; Tenmina never asks for card details. This is only for Tenmina's own
   fees (RUL-01). */
import { useParams, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { Button, Money, ProblemBox, Skeleton, useSession } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { useAct, useApi, words } from '@/components/roles/kit';

type Info = { payment_id: string; provider_ref: string; merchant: string; amount: MoneyT; method: string; status: string; outcomes: string[]; note: string };

function Checkout() {
  const { id } = useParams<{ id: string }>();
  const back = useSearchParams().get('return') || '/';
  const safeBack = back.startsWith('/') && !back.startsWith('//') ? back : '/';
  const { me, loading } = useSession();
  const api = useApi();
  const act = useAct();
  const [info, setInfo] = useState<Info | null>(null);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => {
    if (!me) return;
    act.run('load', async () => setInfo(await api<Info>('GET', `/v1/payments/${id}/fake-checkout`)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, id]);
  if (loading) return <Skeleton />;
  if (!me) return <div className="stack"><h1>Sign in to pay</h1><Link className="btn btn-primary" href={`/login?next=${encodeURIComponent(`/checkout/${id}?return=${safeBack}`)}`}>Sign in</Link></div>;
  return (
    <div className="stack" style={{ maxWidth: 520 }}>
      <p className="label" style={{ margin: 0 }}>Test payment page</p>
      <h1>Pay Tenmina&apos;s fee</h1>
      {info ? (
        <>
          <div className="card-ink stack">
            <span>{info.merchant}</span>
            <strong style={{ fontSize: 28 }}><Money value={info.amount} /></strong>
            <span className="muted">By {words(info.method)} · <span className="mono">{info.provider_ref}</span></span>
          </div>
          <div className="banner-info">{info.note}</div>
          {done || info.status !== 'initiated' ? (
            <div className="stack">
              <strong>Payment {words(done ?? info.status).toLowerCase()}.</strong>
              <Link className="btn btn-primary" href={safeBack}>Continue</Link>
            </div>
          ) : (
            <div className="stack">
              {info.outcomes.map((o) => (
                <Button key={o} variant={o === 'succeed' || o === 'success' ? 'primary' : 'ghost'} busy={act.busy === o} onClick={() => act.run(o, async () => {
                  const p = await api<{ status: string }>('POST', `/v1/payments/${id}/fake-checkout`, { outcome: o });
                  setDone(p.status);
                })}>{words(o)}</Button>
              ))}
            </div>
          )}
        </>
      ) : act.busy ? <Skeleton /> : null}
      <ProblemBox error={act.error} />
    </div>
  );
}

export default function CheckoutPage() {
  return <Suspense><Checkout /></Suspense>;
}
