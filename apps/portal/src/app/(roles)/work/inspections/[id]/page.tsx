'use client';
/* A milestone inspection (US-MOB-007, RUL-10): confirm you have no link to the contractor, answer every
   checklist item, then pass or fail. Defects need photos taken in Tenmina Field. */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Button, Card, Field, KV, Money, ProblemBox, Skeleton, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { PageHead, Section, useAct, useApi, words } from '@/components/roles/kit';

type Inspection = {
  id: string; kind: string; concern: string; scheduled_for: string | null; checklist: { key: string; label: string }[]; status: string;
  outcome: string; defect_value: MoneyT | null; reason: string; note: string; declared_no_link_at: string | null; recorded_at: string | null;
  defects: { id: string; description: string; value: MoneyT; status: string }[]; independence_statement: string; inspector_name: string | null;
};

export default function InspectionPage() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Inspection>(`/v1/inspections/${id}`);
  const api = useApi();
  const act = useAct();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [outcome, setOutcome] = useState('');
  const [reason, setReason] = useState('');
  const [linkReason, setLinkReason] = useState('');
  const i = q.data;
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !i) return <ProblemBox error={q.error ?? 'Inspection not found.'} />;
  const recorded = !!i.recorded_at;
  const complete = i.checklist.every((c) => answers[c.key]);

  return (
    <div className="stack">
      <PageHead back={{ href: '/work/field', label: 'Visits' }} label={`${words(i.kind)} inspection`} title="Inspection" />
      <div className="row"><Status value={i.status} needsYou={!recorded} /></div>
      <Card><KV items={[['Planned for', i.scheduled_for ? <When value={i.scheduled_for} /> : 'Not set'], ['Concern', i.concern || '—'], ['Recorded', i.recorded_at ? <When value={i.recorded_at} withTime /> : 'Not yet']]} /></Card>

      {!i.declared_no_link_at && !recorded ? (
        <Section title="Independence">
          <div className="card-ink stack">
            <p style={{ margin: 0 }}>You may inspect only if you have no link to this contractor: no family tie, no business, no money between you (RUL-10).</p>
            <Button variant="primary" busy={act.busy === 'nolink'} onClick={() => act.run('nolink', async () => { await api('POST', `/v1/inspections/${id}/declaration`, { has_link: false }); await q.mutate(); }, 'Recorded.')}>I have no link to this contractor</Button>
            <Field label="Or declare a link"><Textarea value={linkReason} onChange={(e) => setLinkReason(e.target.value)} placeholder="Say what the link is" /></Field>
            <Button variant="ghost" style={{ color: '#fff' }} disabled={!linkReason.trim()} busy={act.busy === 'link'} onClick={() => act.run('link', async () => { await api('POST', `/v1/inspections/${id}/declaration`, { has_link: true, reason: linkReason }); await q.mutate(); }, 'Link declared. A case manager will reassign this inspection.')}>Declare a link</Button>
          </div>
        </Section>
      ) : i.declared_no_link_at ? <p className="muted">{i.independence_statement}</p> : null}

      {recorded ? (
        <Section title="Result">
          <Card className="stack">
            <strong>{words(i.outcome)}</strong>
            {i.reason ? <p style={{ margin: 0 }}>{i.reason}</p> : null}
            {i.defects.map((d) => <div key={d.id} className="spread"><span>{d.description}</span><span><Money value={d.value} /> · {words(d.status)}</span></div>)}
          </Card>
        </Section>
      ) : i.declared_no_link_at ? (
        <Section title="Checklist">
          <Card className="stack">
            {i.checklist.map((c) => (
              <Field key={c.key} label={c.label}>
                <div className="seg" role="group" aria-label={c.label}>
                  {[['ok', 'Meets the drawing'], ['not_ok', 'Does not'], ['na', 'Not applicable']].map(([v, l]) => <button key={v} type="button" aria-pressed={answers[c.key] === v} onClick={() => setAnswers({ ...answers, [c.key]: v })}>{l}</button>)}
                </div>
              </Field>
            ))}
            <Field label="Result">
              <div className="seg" role="group" aria-label="Result">
                <button type="button" aria-pressed={outcome === 'pass'} onClick={() => setOutcome('pass')}>Pass</button>
                <button type="button" aria-pressed={outcome === 'fail'} onClick={() => setOutcome('fail')}>Fail</button>
              </div>
            </Field>
            {outcome === 'fail' ? <Field label="Why it failed"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field> : null}
            <Blocked title="Pass with defects">Each defect needs a photo taken with Tenmina Field's camera. Record that result in the app.</Blocked>
            <Button variant="primary" block disabled={!complete || !outcome || (outcome === 'fail' && !reason.trim())} busy={act.busy === 'submit'} onClick={() => act.run('submit', async () => {
              await api('POST', '/v1/mobile/inspections', {
                client_submission_id: `web-${id}-${Date.now()}`, subject_type: 'milestone_inspection', subject_id: id, outcome,
                checklist: i.checklist.map((c) => ({ key: c.key, result: answers[c.key] })), reason, note: '',
              });
              await q.mutate();
            }, 'Result submitted.')}>Submit result</Button>
          </Card>
        </Section>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
