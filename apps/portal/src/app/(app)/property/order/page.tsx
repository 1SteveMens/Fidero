'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, Money, ProblemBox, Skeleton, Steps, useGet, useSession } from '@tenmina/web-ui';
import { PageHead, RadioCard, useAction, type Any } from '@/components/kit';
import { orderSteps } from '@/lib/steps';

/** W-03 · SCR-PTL-06: land or building, and the tier. Prices come from the server, never the page. */
function Step1() {
  const { me } = useSession();
  const country = me?.home_country || 'GH';
  const router = useRouter();
  const kind = useSearchParams().get('kind') || 'verification';
  const tiers = useGet<Any[]>('/v1/catalogue/tiers', { country, kind });
  const products = useGet<Any[]>('/v1/catalogue/products', { country });
  const [assetType, setAssetType] = useState('plot');
  const [tier, setTier] = useState('');
  const a = useAction();
  const product = (products.data ?? []).find((p: Any) => p.kind === kind);
  const order = ['basic', 'standard', 'premium'];
  const list = [...(tiers.data ?? [])].sort((x: Any, y: Any) => order.indexOf(x.tier) - order.indexOf(y.tier));
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label="Order a check · step 1 of 4" title="What should we check?" />
      <Steps items={orderSteps(0).slice(0, 4)} />
      {product ? <p className="muted">{product.description}</p> : null}
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="label" style={{ marginBottom: 8 }}>Land or building</legend>
        <RadioCard name="asset" checked={assetType === 'plot'} onChange={() => setAssetType('plot')}><strong>Land</strong><div className="muted">A plot, with or without a fence.</div></RadioCard>
        <RadioCard name="asset" checked={assetType === 'building'} onChange={() => setAssetType('building')}><strong>A building</strong><div className="muted">A house or flat you want to buy or already own.</div></RadioCard>
      </fieldset>
      {product?.tiered !== false ? (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ marginBottom: 8 }}>How deep a check</legend>
          {tiers.isLoading ? <Skeleton /> : list.map((t: Any) => (
            <RadioCard key={t.tier} name="tier" checked={tier === t.tier} onChange={() => setTier(t.tier)}>
              <div className="spread"><strong>{t.tier_name}</strong><Money value={t.price} /></div>
              <div className="muted" style={{ fontSize: 14 }}>
                <Money value={t.local_price} /> {t.guide_for_you ? <>· about <Money value={t.guide_for_you} /> (a guide, not a charge)</> : null}
                {t.turnaround_days ? <> · about {t.turnaround_days} working days</> : null}
              </div>
            </RadioCard>
          ))}
          <ProblemBox error={tiers.error} />
        </fieldset>
      ) : null}
      <p className="muted" style={{ fontSize: 14 }}>You pay Tenmina&apos;s fee for the work, whatever the verdict. Any money for the land itself goes to a licensed bank, never to Tenmina.</p>
      <ProblemBox error={a.error} />
      <Button variant="primary" block busy={!!a.busy} disabled={product?.tiered !== false && !tier}
        onClick={() => a.run('create', () => a.post<Any>('/v1/orders', { country, kind, draft: true, tier: tier || undefined, asset: { type: assetType } }), undefined, (o) => router.push(`/property/orders/${o.id}?step=2`))}>
        Next: the {assetType === 'plot' ? 'plot' : 'building'}
      </Button>
    </div>
  );
}

export default function OrderStart() {
  return <Suspense><Step1 /></Suspense>;
}
