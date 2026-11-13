'use client';
import { KV, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { Copy, Ink, PageHead } from '@/components/kit';
import type { Any } from '@/components/kit';

/** FR-ORD-006: the client's referral code. Figures are working assumptions set by Tenmina. */
export default function Referral() {
  const q = useGet<Any>('/v1/me/referral-code');
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Your referral code" sub="Share it. The person you refer gets a discount on their first check, and you get a reward when they pay." />
      {q.isLoading ? <Skeleton /> : q.data ? (
        <section className="card stack">
          <div className="row"><span className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{q.data.code}</span><Copy value={q.data.code} /></div>
          <KV items={[['Discount for them', `${Number(q.data.discount_pct)}%`], ['Reward for you', <Money key="r" value={q.data.reward} />], ['Used', String(q.data.uses)], ['Valid until', q.data.valid_until ? <When key="v" value={q.data.valid_until} /> : 'No end date']]} />
        </section>
      ) : <ProblemBox error={q.error} />}
    </Ink>
  );
}
