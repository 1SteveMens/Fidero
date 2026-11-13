'use client';
/* Metered usage for a month (FR-PTR-004). */
import { useEffect, useState } from 'react';
import { Card, Field, Input, ProblemBox, Skeleton } from '@tenmina/web-ui';
import { PageHead, useAct, words } from '@/components/roles/kit';
import { PartnerBar, usePartner } from '@/components/roles/partner';

type Usage = { partner: string; month: string; call_count: number; billable_count: number; order_count: number; by_result: Record<string, number>; closed: boolean };

export default function PartnerUsage() {
  const { call } = usePartner();
  const act = useAct();
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [u, setU] = useState<Usage | null>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { act.run('u', async () => setU(await call<Usage>('GET', `/v1/partner/usage?month=${month}`))); }, [month]);
  return (
    <div className="stack">
      <PartnerBar />
      <PageHead label="Partner" title="Usage">Calls counted for billing. Figures come from Tenmina&apos;s meter.</PageHead>
      <Field label="Month"><Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
      {act.busy ? <Skeleton /> : u ? (
        <Card>
          <div className="statline"><span>Calls</span><span className="v">{u.call_count}</span></div>
          <div className="statline"><span>Billable</span><span className="v">{u.billable_count}</span></div>
          <div className="statline"><span>Orders</span><span className="v">{u.order_count}</span></div>
          {Object.entries(u.by_result).map(([k, v]) => <div key={k} className="statline"><span className="muted">{words(k)}</span><span className="v">{v}</span></div>)}
          <p className="muted" style={{ marginBottom: 0 }}>{u.closed ? 'This month is closed and invoiced.' : 'This month is still open.'}</p>
        </Card>
      ) : null}
      <ProblemBox error={act.error} />
    </div>
  );
}
