'use client';
/* Defects from inspections (FR-BLD-006): fix each, send the evidence, and the held value is released
   after the inspector confirms. */
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, Money, ProblemBox, Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, EvidenceLink, FilePick, Loaded, PageHead, items, useAct, useApi, type Page } from '@/components/roles/kit';
import { uploadEvidence } from '@/components/roles/files';
import type { Defect } from '@/components/roles/build';

export default function Defects() {
  const q = useGet<Page<Defect>>('/v1/defects');
  return (
    <div className="stack">
      <PageHead label="Building" title="Defects">Found at inspection. The value of each is held back until it is fixed and confirmed.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((x) => <DefectCard key={x.id} d={x} onDone={() => q.mutate()} />) : <EmptyText>No defects. Good work.</EmptyText>}</Loaded>
    </div>
  );
}

function DefectCard({ d, onDone }: { d: Defect; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState('');
  return (
    <Card className="stack">
      <div className="spread"><strong>{d.description}</strong><Money value={d.value} /></div>
      <div className="row">{d.status === 'closed' ? <Chip tone="lime">✓ Closed <When value={d.closed_at} /></Chip> : <Status value={d.status} needsYou={d.status === 'open'} />}</div>
      <div className="row">{d.photo_evidence_ids.map((e, n) => <EvidenceLink key={e} id={e} label={`Inspector's photo ${n + 1}`} />)}</div>
      {d.status === 'fixed' ? <span className="muted">Sent <When value={d.fixed_at} />. The inspector confirms next.</span> : null}
      {d.status === 'open' ? (
        <>
          <FilePick label="Photo of the fix" file={file} onFile={setFile} accept="image/*" hint="If the photo must be sealed, send it from Tenmina Field." />
          <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Button variant="action" disabled={!file} busy={act.busy === 'c'} onClick={() => act.run('c', async () => {
            const ev = await uploadEvidence(file!, { type: 'defect', id: d.id, role: 'defect_fixed' });
            await api('POST', `/v1/defects/${d.id}/close`, { evidence_ids: [ev.id], note });
            onDone();
          }, 'Sent. The inspector confirms the fix.')}>Send the fix</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
