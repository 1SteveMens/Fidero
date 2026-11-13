'use client';
/* Claims (US-INS-004): only the insurer decides and pays claims. Each update you record is shown to the
   client as "The insurer says: …" (RUL-25). */
import { useState } from 'react';
import { Button, Card, Field, ProblemBox, Select, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { EmptyText, FilePick, Loaded, PageHead, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { toBase64 } from '@/components/roles/files';
import { InsurerLine, type Claim } from '@/components/roles/insurer';

const STATUSES = ['received', 'assessing', 'more_information', 'paid', 'declined'];

export default function InsurerClaims() {
  const q = useGet<Page<Claim>>('/v1/insurance/claims');
  return (
    <div className="stack">
      <PageHead label="Insurer" title="Claims">Claims clients started through Tenmina. Tenmina never decides a claim.</PageHead>
      <InsurerLine />
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((c) => <ClaimCard key={c.id} c={c} onDone={() => q.mutate()} />) : <EmptyText>No claims.</EmptyText>}</Loaded>
    </div>
  );
}

function ClaimCard({ c, onDone }: { c: Claim; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [st, setSt] = useState(c.insurer_status || 'received');
  const [note, setNote] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const closed = c.insurer_status === 'paid' || c.insurer_status === 'declined';
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label mono">{c.insurer_reference}</div><strong>{c.description}</strong></div><Status value={c.insurer_status || 'new'} needsYou={!c.insurer_status || c.insurer_status === 'received'} /></div>
      <span className="muted" style={{ fontSize: 14 }}>{c.event_date ? <>Happened <When value={c.event_date} /> · </> : null}sent to you <When value={c.submitted_to_insurer_at} /></span>
      {c.updates.map((u) => <div key={u.id} style={{ fontSize: 14, borderLeft: '3px solid var(--color-line-strong)', paddingLeft: 10 }}><strong>{words(u.insurer_status)}</strong> · <When value={u.created_at} withTime /><div>{u.note}</div></div>)}
      {!closed ? (
        <>
          <Field label="Update"><Select value={st} onChange={(e) => setSt(e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{words(s)}</option>)}</Select></Field>
          <Field label="Note to the client"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <FilePick label="Letter or document (optional)" file={file} onFile={setFile} accept="application/pdf,image/*" />
          <Button variant="action" disabled={!note.trim()} busy={act.busy === 'u'} onClick={() => act.run('u', async () => {
            await api('POST', `/v1/insurance/claims/${c.id}/updates`, { insurer_status: st, note, ...(file ? { document_base64: await toBase64(file), content_type: file.type || 'application/pdf', file_name: file.name } : {}) });
            setNote(''); setFile(null); onDone();
          }, 'Update sent to the client.')}>Send update</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
