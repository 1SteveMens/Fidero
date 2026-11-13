'use client';
/* Confirm a visit or delivery (SCR-PTL-45, W-31, US-CARE-004) for a family member with an account: the
   code sent to their own phone confirms; "it did not happen" needs no code. The carer never sees the
   code and is paid only for confirmed visits (RUL-23). No amounts are shown. */
import { useState } from 'react';
import { Button, Card, Chip, CodeBoxes, Field, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { EmptyText, PageHead, Section, useAct, useApi } from '@/components/roles/kit';

type Conf = { id: string; subject_type: string; subject_id: string; purpose: string; summary: string; channel: string; expires_at: string; status: string; attempts_left: number; confirmed_at: string | null; confirmed_via: string; created_at: string };

const DONE: Record<string, string> = {
  confirmed: 'You confirmed it.', disputed: 'You said it did not happen. Tenmina will call you.', locked: 'Locked after too many wrong codes. Tenmina will call you to confirm.',
  expired: 'This has expired. Tenmina will call you.', cancelled: 'Cancelled. Nothing to do.', pending_check: 'Being checked by Tenmina.',
};

export default function FamilyMember() {
  const q = useGet<Conf[]>('/v1/me/confirmations');
  const pending = (q.data ?? []).filter((c) => c.status === 'pending');
  const done = (q.data ?? []).filter((c) => c.status !== 'pending');
  return (
    <div className="stack confirm-page">
      <PageHead label="Confirm" title="Did it happen?">Your answer tells Tenmina whether to pay. The client abroad sees it.</PageHead>
      {q.isLoading ? <Skeleton /> : null}
      <ProblemBox error={q.error} />
      {!q.isLoading && !pending.length ? <EmptyText>Nothing to confirm right now. We send you a code when there is.</EmptyText> : null}
      {pending.map((c) => <Ask key={c.id} c={c} onDone={() => q.mutate()} />)}
      {done.length ? (
        <Section title="Answered">
          {done.map((c) => (
            <Card key={c.id} className="stack" style={{ gap: 4, fontSize: 16 }}>
              <strong>{c.summary ? c.summary.charAt(0).toUpperCase() + c.summary.slice(1) : (c.purpose === 'care_visit' ? 'Care visit' : 'Delivery')}</strong>
              <div className="row">{c.status === 'confirmed' ? <Chip tone="lime">✓ Confirmed</Chip> : <Chip>{c.status.replace(/_/g, ' ')}</Chip>}{c.confirmed_at ? <span className="muted"><When value={c.confirmed_at} withTime /></span> : null}</div>
              <span className="muted" style={{ fontSize: 15 }}>{DONE[c.status] ?? ''}</span>
            </Card>
          ))}
        </Section>
      ) : null}
    </div>
  );
}

function Ask({ c, onDone }: { c: Conf; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [code, setCode] = useState('');
  const what = c.purpose === 'care_visit' ? 'the visit' : 'the delivery';
  return (
    <Card className="stack">
      <div className="big-q">Did {what} happen?</div>
      {c.summary ? <div style={{ fontSize: 18 }}>{c.summary.charAt(0).toUpperCase() + c.summary.slice(1)}</div> : null}
      <span className="muted" style={{ fontSize: 16 }}>Answer by <When value={c.expires_at} withTime />.</span>
      <Field label="Code we sent to your phone"><CodeBoxes value={code} onChange={setCode} /></Field>
      <Button variant="action" block disabled={code.length !== 6} busy={act.busy === 'y'} onClick={() => act.run('y', async () => {
        await api('POST', '/v1/family-confirmations/codes', { subject_type: c.subject_type, subject_id: c.subject_id, code });
        onDone();
      }, 'Thank you. Confirmed.')}>Yes, {what} happened</Button>
      <Button variant="ghost" block busy={act.busy === 'n'} onClick={() => act.run('n', async () => { await api('POST', `/v1/me/confirmations/${c.id}/disputes`); onDone(); }, 'We are sorry. Tenmina will call you today.')}>No, it did not happen</Button>
      <span className="muted" style={{ fontSize: 15 }}>{c.attempts_left < 5 ? `${c.attempts_left} tries left. ` : ''}The code locks after 5 wrong tries.</span>
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
