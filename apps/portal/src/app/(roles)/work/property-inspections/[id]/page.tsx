'use client';
/* A property inspection for property management (FR-PMG-003, FR-PMG-005). Room photos are taken in
   Tenmina Field; this page shows the job and records an outcome where no photo is needed. */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Field, KV, ProblemBox, Select, Skeleton, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { PageHead, Section, useAct, useApi, words } from '@/components/roles/kit';

type PmgInspection = { id: string; property_title: string; kind: string; scheduled_for: string | null; status: string; outcome: string; condition_rating: string; notes: string; submitted_at: string | null; photos: unknown[]; repair: string | null };

export default function PropertyInspection() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<PmgInspection>(`/v1/pmg-inspections/${id}`);
  const api = useApi();
  const act = useAct();
  const [outcome, setOutcome] = useState('pass');
  const [cond, setCond] = useState('good');
  const [notes, setNotes] = useState('');
  const i = q.data;
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !i) return <ProblemBox error={q.error ?? 'Inspection not found.'} />;
  const done = !!i.submitted_at;
  return (
    <div className="stack">
      <PageHead back={{ href: '/work/field', label: 'Visits' }} label={`${words(i.kind)} inspection`} title={i.property_title} />
      <div className="row"><Status value={i.status} needsYou={!done} /></div>
      <Card><KV items={[['Planned for', i.scheduled_for ? <When value={i.scheduled_for} /> : 'Not set'], ['For a repair', i.repair ? 'Yes' : 'No'], ['Submitted', i.submitted_at ? <When value={i.submitted_at} withTime /> : 'Not yet']]} /></Card>
      {done ? (
        <Card className="stack"><strong>{words(i.outcome)}</strong><span>Condition: {words(i.condition_rating)}</span>{i.notes ? <p style={{ margin: 0 }}>{i.notes}</p> : null}</Card>
      ) : (
        <Section title="Record the visit">
          <div className="banner-info">Take the room photos in Tenmina Field. They are sealed at capture so the owner can trust them.</div>
          <Card className="stack">
            <Field label="Outcome"><Select value={outcome} onChange={(e) => setOutcome(e.target.value)}><option value="pass">Pass</option><option value="pass_with_defects">Pass with defects</option><option value="fail">Fail</option></Select></Field>
            <Field label="Condition"><Select value={cond} onChange={(e) => setCond(e.target.value)}><option value="good">Good</option><option value="fair">Fair</option><option value="poor">Poor</option></Select></Field>
            <Field label="Notes"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
            <Button variant="primary" busy={act.busy === 's'} onClick={() => act.run('s', async () => { await api('POST', `/v1/pmg-inspections/${id}/results`, { outcome, condition_rating: cond, notes }); await q.mutate(); }, 'Recorded.')}>Submit</Button>
          </Card>
        </Section>
      )}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
