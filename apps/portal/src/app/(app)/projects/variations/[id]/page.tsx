'use client';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, KV, Money, ProblemBox, Skeleton, Textarea, When, useGet } from '@tenmina/web-ui';
import { PageHead, Proof, useAction, words, type Any } from '@/components/kit';

/** SCR-PTL-24: agree or decline a change to the work before it is done (FR-BLD-008, RUL-19). */
export default function Variation() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/variations/${id}`);
  const a = useAction();
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={5} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const v = q.data;
  const open = v.status === 'proposed' && !v.client_agreed_at;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: `/projects/${v.project_id}`, label: 'The project' }} label={`Change to the work · ${words(v.status)}`} title={v.description} />
      <KV items={[['Cost', <Money key="c" value={v.cost_change} />], ['Time', `${v.time_effect_days} day(s)`], ['Contractor agreed', v.contractor_agreed_at ? <When key="k" value={v.contractor_agreed_at} /> : 'Not yet'], ['You agreed', v.client_agreed_at ? <When key="y" value={v.client_agreed_at} /> : 'Not yet']]} />
      {v.agreed_at ? <Proof>Agreed by both <When value={v.agreed_at} /></Proof> : null}
      {v.decline_reason ? <p>Declined: {v.decline_reason}</p> : null}
      {open ? (
        <>
          <p style={{ margin: 0 }}>The work changes only once you and the contractor both agree. The milestone amount changes with it.</p>
          <Button variant="action" busy={a.busy === 'y'} onClick={() => a.run('y', () => a.post(`/v1/variations/${id}/agreements`, { decision: 'agree' }), 'Agreed', () => q.mutate())}>Agree to the change</Button>
          <Field label="If you decline, why"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <Button variant="ghost" busy={a.busy === 'n'} onClick={() => a.run('n', () => a.post(`/v1/variations/${id}/agreements`, { decision: 'decline', reason }), 'Declined', () => q.mutate())}>Decline</Button>
        </>
      ) : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}
