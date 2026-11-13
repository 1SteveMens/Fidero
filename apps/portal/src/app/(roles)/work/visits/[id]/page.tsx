'use client';
/* A carer's visit (US-CARE-003, US-CARE-006): plan items done, not done or not applicable, and a concern
   that reaches the client and a reviewer the same day. Check-in and out stay in Tenmina Field (RUL-23). */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, KV, ProblemBox, Select, Skeleton, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { FilePick, PageHead, Section, useAct, useApi, words } from '@/components/roles/kit';
import { uploadEvidence } from '@/components/roles/files';

type Item = { key: string; kind: string; label: string; photo_required: boolean; photo_allowed: boolean; reading_required: boolean; reading_kind: string; outcome: string; reason: string; evidence: string | null; recorded_at: string | null };
type Visit = {
  id: string; plan_reference: string; family_member: { full_name: string; relationship: string }; window_start: string; window_end: string; status: string;
  check_in: { at: string; within_radius: boolean } | null; check_out: { at: string } | null; items: Item[];
};

export default function VisitPage() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Visit>(`/v1/mobile/visits/${id}`);
  const api = useApi();
  const act = useAct();
  const [kind, setKind] = useState('welfare');
  const [sev, setSev] = useState('medium');
  const [text, setText] = useState('');
  const v = q.data;
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !v) return <ProblemBox error={q.error ?? 'Visit not found.'} />;
  const open = v.status === 'checked_in';
  return (
    <div className="stack">
      <PageHead back={{ href: '/work/field', label: 'Visits' }} label={v.plan_reference} title={`Visit ${v.family_member.full_name}`} />
      <div className="row"><Status value={v.status} needsYou={v.status === 'scheduled' || open} /></div>
      <Card>
        <KV items={[
          ['Window', <span key="w"><When value={v.window_start} withTime /> to <When value={v.window_end} withTime /></span>],
          ['Checked in', v.check_in ? <span key="i"><When value={v.check_in.at} withTime />{v.check_in.within_radius ? '' : ' (away from the address)'}</span> : 'Not yet'],
          ['Checked out', v.check_out ? <When key="o" value={v.check_out.at} withTime /> : 'Not yet'],
        ]} />
      </Card>
      {!v.check_in ? <div className="banner-info">Check in at the address with Tenmina Field. Then come back here or use the app for the plan.</div> : null}
      <Section title="Plan for this visit">
        {v.items.map((it) => <ItemCard key={it.key} visitId={v.id} it={it} canRecord={open} onDone={() => q.mutate()} />)}
      </Section>
      <Section title="Raise a concern">
        <Card className="stack">
          <p className="muted" style={{ margin: 0 }}>About health, safety or welfare. The family and a Tenmina reviewer hear today.</p>
          <Field label="About"><Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="health">Health</option><option value="safety">Safety</option><option value="welfare">Welfare</option></Select></Field>
          <Field label="How serious"><Select value={sev} onChange={(e) => setSev(e.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option></Select></Field>
          <Field label="What you saw"><Textarea value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <Button variant="dark" disabled={!text.trim()} busy={act.busy === 'c'} onClick={() => act.run('c', async () => { await api('POST', `/v1/mobile/visits/${id}/concerns`, { kind, severity: sev, narrative: text }); setText(''); }, 'Concern sent. Tenmina will act on it today.')}>Send concern</Button>
          <ProblemBox error={act.error} />
        </Card>
      </Section>
      {act.toast}
    </div>
  );
}

function ItemCard({ visitId, it, canRecord, onDone }: { visitId: string; it: Item; canRecord: boolean; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState('');
  const [reading, setReading] = useState('');
  async function record(outcome: string) {
    await act.run(outcome, async () => {
      let evidence_id: string | undefined;
      if (outcome === 'done' && file) evidence_id = (await uploadEvidence(file, { type: 'care_visit', id: visitId, role: it.kind })).id;
      await api('PUT', `/v1/mobile/visits/${visitId}/items/${it.key}`, {
        outcome, reason: outcome === 'not_done' ? reason : '', evidence_id,
        reading: it.reading_required && reading ? { kind: it.reading_kind, value: reading } : undefined,
      });
      onDone();
    }, 'Recorded.');
  }
  return (
    <Card className="stack">
      <div className="spread"><strong>{it.label}</strong>{it.outcome !== 'pending' ? <Chip tone={it.outcome === 'done' ? 'lime' : undefined}>{words(it.outcome)}</Chip> : null}</div>
      {it.recorded_at ? <span className="muted" style={{ fontSize: 14 }}>Recorded <When value={it.recorded_at} withTime />{it.reason ? `: ${it.reason}` : ''}</span> : null}
      {canRecord && it.outcome === 'pending' ? (
        <>
          {it.photo_required ? <FilePick label="Agreed photo" file={file} onFile={setFile} accept="image/*" hint="If the photo must be sealed, take it in Tenmina Field." /> : null}
          {it.reading_required ? <Field label={`Reading (${words(it.reading_kind)})`}><Input value={reading} onChange={(e) => setReading(e.target.value)} /></Field> : null}
          <div className="row">
            <Button variant="primary" busy={act.busy === 'done'} disabled={(it.photo_required && !file) || (it.reading_required && !reading)} onClick={() => record('done')}>Done</Button>
            <Button variant="ghost" busy={act.busy === 'not_applicable'} onClick={() => record('not_applicable')}>Not needed today</Button>
          </div>
          <Field label="Not done? Say why"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <Button variant="ghost" disabled={!reason.trim()} busy={act.busy === 'not_done'} onClick={() => record('not_done')}>Not done</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
