'use client';
/* Insurer: applications Tenmina passed on (US-INS-002). Accept with the policy document, or decline. */
import { useState } from 'react';
import { Button, Card, Field, Input, ProblemBox, Select, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { EmptyText, FilePick, Loaded, PageHead, Section, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { toBase64 } from '@/components/roles/files';
import { InsurerLine, type Application } from '@/components/roles/insurer';

export default function InsurerApplications() {
  const q = useGet<Page<Application>>('/v1/insurance/applications');
  const all = items(q.data);
  const open = all.filter((a) => a.status === 'submitted');
  return (
    <div className="stack">
      <PageHead label="Insurer" title="Applications">Applications from Tenmina clients for their family members.</PageHead>
      <InsurerLine />
      <Loaded q={q}>{() => (
        <>
          <Section title="To decide">{open.length ? open.map((a) => <Decide key={a.id} a={a} onDone={() => q.mutate()} />) : <EmptyText>No applications waiting for you.</EmptyText>}</Section>
          <Section title="Decided and drafts">
            {all.filter((a) => !open.includes(a)).map((a) => (
              <Card key={a.id} className="spread"><div><div className="label">{a.insurer_reference || 'No reference yet'}</div><strong>{a.product_name}</strong><div className="muted" style={{ fontSize: 14 }}>{a.status_text}</div></div><Status value={a.status} /></Card>
            ))}
          </Section>
        </>
      )}</Loaded>
    </div>
  );
}

function Decide({ a, onDone }: { a: Application; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [outcome, setOutcome] = useState('accepted');
  const [num, setNum] = useState('');
  const [starts, setStarts] = useState(new Date().toISOString().slice(0, 10));
  const [renews, setRenews] = useState('');
  const [contact, setContact] = useState('');
  const [note, setNote] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const ok = outcome === 'declined' ? !!note.trim() : !!(num && starts && renews && file);
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label">{a.insurer_reference}</div><strong>{a.product_name}</strong></div><Status value={a.status} needsYou /></div>
      <span className="muted" style={{ fontSize: 14 }}>Sent to you <When value={a.submitted_to_insurer_at} withTime /> · premium route: {words(a.premium_route)}</span>
      {Object.keys(a.answers).length ? <div style={{ fontSize: 14 }}>{Object.entries(a.answers).map(([k, v]) => <div key={k}>{words(k)}: <strong>{String(v)}</strong></div>)}</div> : null}
      <Field label="Your decision"><Select value={outcome} onChange={(e) => setOutcome(e.target.value)}><option value="accepted">Accept and issue a policy</option><option value="declined">Decline</option></Select></Field>
      {outcome === 'accepted' ? (
        <>
          <Field label="Policy number"><Input value={num} onChange={(e) => setNum(e.target.value)} /></Field>
          <div className="grid2" style={{ gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <Field label="Starts"><Input type="date" value={starts} onChange={(e) => setStarts(e.target.value)} /></Field>
            <Field label="Renews"><Input type="date" value={renews} onChange={(e) => setRenews(e.target.value)} /></Field>
          </div>
          <Field label="Claims contact"><Input value={contact} onChange={(e) => setContact(e.target.value)} /></Field>
          <FilePick label="Policy document (PDF)" file={file} onFile={setFile} accept="application/pdf" />
        </>
      ) : null}
      <Field label={outcome === 'declined' ? 'Reason the client will see' : 'Note (optional)'}><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <Button variant="action" disabled={!ok} busy={act.busy === 'd'} onClick={() => act.run('d', async () => {
        await api('POST', `/v1/insurance/applications/${a.id}/outcomes`, {
          outcome, note, ...(outcome === 'accepted' ? { policy_number: num, starts_on: starts, renews_on: renews, claim_contact: contact, document_base64: await toBase64(file!), content_type: 'application/pdf', file_name: file!.name } : {}),
        });
        onDone();
      }, 'Decision recorded. The client is told.')}>Record decision</Button>
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
