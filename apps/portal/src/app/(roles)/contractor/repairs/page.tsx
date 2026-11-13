'use client';
/* Repairs you were chosen for on managed properties (US-PMG-005): report the work done with photos.
   You are paid only after an inspection. */
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, ProblemBox, Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, FilePick, Loaded, PageHead, items, useAct, useApi, type Page } from '@/components/roles/kit';
import { uploadEvidence } from '@/components/roles/files';

type Repair = { id: string; property_title: string; title: string; description: string; urgent: boolean; status: string; work_done_at: string | null; paid_at: string | null; escrow_reference: string | null; created_at: string };

export default function ContractorRepairs() {
  const q = useGet<Page<Repair>>('/v1/repairs');
  return (
    <div className="stack">
      <PageHead label="Building" title="Repairs">Repairs where the owner approved your quote. The bank holds the money; you are paid after an inspection.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((r) => <RepairCard key={r.id} r={r} onDone={() => q.mutate()} />) : <EmptyText>No repairs for you.</EmptyText>}</Loaded>
    </div>
  );
}

function RepairCard({ r, onDone }: { r: Repair; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState('');
  const ready = r.status === 'funded' || r.status === 'in_progress';
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label">{r.property_title}</div><strong>{r.title}</strong></div>{r.paid_at ? <Chip tone="lime">✓ Paid</Chip> : <Status value={r.status} needsYou={ready} />}</div>
      <p style={{ margin: 0 }}>{r.description}</p>
      {r.work_done_at ? <span className="muted">Work reported done <When value={r.work_done_at} />.</span> : null}
      {ready && !r.work_done_at ? (
        <>
          <FilePick label="Photo of the finished work" file={file} onFile={setFile} accept="image/*" />
          <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Button variant="action" disabled={!file} busy={act.busy === 'w'} onClick={() => act.run('w', async () => {
            const ev = await uploadEvidence(file!, { type: 'repair', id: r.id, role: 'work_done' });
            await api('POST', `/v1/repairs/${r.id}/work-done`, { evidence_ids: [ev.id], note });
            onDone();
          }, 'Reported. An inspector checks the work.')}>The work is done</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
