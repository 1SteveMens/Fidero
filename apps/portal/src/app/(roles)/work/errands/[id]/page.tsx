'use client';
/* An errand agent's errand (US-TSK-003, US-TSK-005): steps with the acknowledgement or receipt, the
   resulting document and the handover. Official fees go only to the agency's account (RUL-22). */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, Money, ProblemBox, Select, Skeleton, Status, When, useGet } from '@tenmina/web-ui';
import { EvidenceLink, FilePick, PageHead, PayeeLine, Section, useAct, useApi, words } from '@/components/roles/kit';
import { postForm, uploadEvidence } from '@/components/roles/files';
import type { Money as MoneyT } from '@tenmina/api-client';

type Step = { id: string; seq: number; description: string; official_fee: MoneyT; status: string; plain: string; has_acknowledgement: boolean; has_receipt: boolean; acknowledgement_evidence: string | null; receipt_evidence: string | null; needs_documents: string[]; started_at: string | null; done_at: string | null };
type Errand = {
  id: string; reference: string; status: string; name: string; agency_payee: { legal_name: string; last4: string } | null; steps: Step[];
  documents: { key: string; label: string; status: string }[]; due_on: string | null; result_uploaded_at: string | null; result_note: string;
  handover: { method: string; created_at?: string } | null;
};

export default function ErrandPage() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Errand>(`/v1/mobile/errands/${id}`);
  const act = useAct();
  const [result, setResult] = useState<File | null>(null);
  const [method, setMethod] = useState('client');
  const [proof, setProof] = useState('photo');
  const [who, setWho] = useState('');
  const [hfile, setHfile] = useState<File | null>(null);
  const e = q.data;
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !e) return <ProblemBox error={q.error ?? 'Errand not found.'} />;
  const allDone = e.steps.every((s) => s.status === 'done');
  return (
    <div className="stack">
      <PageHead back={{ href: '/work/field', label: 'Visits' }} label={e.reference} title={e.name} />
      <div className="row"><Status value={e.status} />{e.due_on ? <span className="muted">Target <When value={e.due_on} /></span> : null}</div>
      {e.agency_payee ? <div className="banner-info"><PayeeLine planned name={e.agency_payee.legal_name} last4={e.agency_payee.last4} />. Official fees go from the bank to the agency. Never pay them yourself.</div> : null}
      <Section title="Steps">
        {e.steps.map((s) => <StepCard key={s.id} errandId={e.id} s={s} docs={e.documents} onDone={() => q.mutate()} />)}
      </Section>
      <Section title="Resulting document">
        <Card className="stack">
          {e.result_uploaded_at ? <p style={{ margin: 0 }}>Uploaded <When value={e.result_uploaded_at} withTime />. Tenmina checks it before the errand completes.</p> : (
            <>
              <FilePick label="The document you collected" file={result} onFile={setResult} accept="image/*,application/pdf" />
              <Button variant="primary" disabled={!result || !allDone} busy={act.busy === 'res'} onClick={() => act.run('res', async () => {
                const ev = await uploadEvidence(result!, { type: 'errand', id: e.id, role: 'result' });
                await postForm(`/v1/mobile/errands/${e.id}/results`, { evidence_id: ev.id });
                setResult(null); await q.mutate();
              }, 'Document uploaded.')}>Upload the document</Button>
              {!allDone ? <span className="muted">Finish every step first.</span> : null}
            </>
          )}
        </Card>
      </Section>
      {e.result_uploaded_at ? (
        <Section title="Handover">
          <Card className="stack">
            {e.handover ? <p style={{ margin: 0 }}>Handed over to the {words(e.handover.method)}.</p> : (
              <>
                <Field label="Handed to"><Select value={method} onChange={(ev) => setMethod(ev.target.value)}><option value="client">The client</option><option value="representative">The client's representative</option><option value="family_member">A family member</option><option value="courier">A courier</option></Select></Field>
                <Field label={method === 'courier' ? 'Courier and tracking reference' : 'Name of the person'}><Input value={who} onChange={(ev) => setWho(ev.target.value)} /></Field>
                <Field label="Proof"><Select value={proof} onChange={(ev) => setProof(ev.target.value)}><option value="photo">Photo of the handover</option><option value="signature">Signed receipt</option></Select></Field>
                <FilePick label="Photo or signed receipt" file={hfile} onFile={setHfile} accept="image/*,application/pdf" />
                <Button variant="primary" disabled={!hfile || !who.trim()} busy={act.busy === 'h'} onClick={() => act.run('h', async () => {
                  await postForm(`/v1/mobile/errands/${e.id}/handovers`, { method, proof_kind: proof, file: hfile, ...(method === 'courier' ? { courier_name: who } : { receiver_name: who }) });
                  await q.mutate();
                }, 'Handover recorded.')}>Record handover</Button>
              </>
            )}
          </Card>
        </Section>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}

function StepCard({ errandId, s, docs, onDone }: { errandId: string; s: Step; docs: Errand['documents']; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<'acknowledgement' | 'receipt'>(s.has_acknowledgement ? 'receipt' : 'acknowledgement');
  const base = `/v1/mobile/errands/${errandId}/steps/${s.seq}`;
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label">Step {s.seq}</div><strong>{s.description}</strong></div>{s.status === 'done' ? <Chip tone="lime">✓ Done</Chip> : <Status value={s.status} />}</div>
      <span className="muted" style={{ fontSize: 14 }}>{s.plain}</span>
      {Number(s.official_fee.amount) > 0 ? <span>Official fee <Money value={s.official_fee} />, paid by the bank to the agency.</span> : null}
      {s.needs_documents.length ? (
        <div className="row" style={{ gap: 6 }}>
          {s.needs_documents.map((k) => <a key={k} className="btn btn-ghost btn-sm" href="#" onClick={async (ev) => { ev.preventDefault(); await act.run(k, async () => { const l = await api<{ url: string }>('GET', `/v1/mobile/errands/${errandId}/documents/${k}/link`); window.open(l.url, '_blank', 'noopener'); }); }}>{docs.find((d) => d.key === k)?.label ?? words(k)}</a>)}
        </div>
      ) : null}
      <div className="row"><EvidenceLink id={s.acknowledgement_evidence} label="Acknowledgement" /><EvidenceLink id={s.receipt_evidence} label="Receipt" /></div>
      {s.status !== 'done' ? (
        <>
          {!s.started_at ? <Button variant="ghost" busy={act.busy === 'start'} onClick={() => act.run('start', async () => { await api('POST', `${base}/start`); onDone(); }, 'Step started.')}>Start this step</Button> : null}
          <Field label="Upload"><Select value={kind} onChange={(e) => setKind(e.target.value as 'acknowledgement' | 'receipt')}><option value="acknowledgement">Acknowledgement</option><option value="receipt">Receipt</option></Select></Field>
          <FilePick label="Photo of it" file={file} onFile={setFile} accept="image/*,application/pdf" hint="If it must be a sealed photo, take it in Tenmina Field." />
          <Button variant="dark" disabled={!file} busy={act.busy === 'up'} onClick={() => act.run('up', async () => {
            const ev = await uploadEvidence(file!, { type: 'errand_step', id: s.id, role: kind });
            await api('POST', `${base}/receipts`, { kind, evidence_id: ev.id });
            setFile(null); onDone();
          }, 'Uploaded.')}>Upload</Button>
          <Button variant="primary" disabled={!s.has_acknowledgement && !s.has_receipt} busy={act.busy === 'done'} onClick={() => act.run('done', async () => { await api('POST', `${base}/done`); onDone(); }, 'Step done.')}>Mark step done</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
