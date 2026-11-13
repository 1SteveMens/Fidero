'use client';
/* Report sections for lawyers and surveyors (US-RPT-002, US-RPT-005, US-RPT-009): findings, the section
   verdict, signing with name, licence and time after a fresh second factor, section 11 conditions, and
   the signing lawyer's approval (RUL-03). Reports are shown on black (03, 6.1a). */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, KV, ProblemBox, Select, Skeleton, Status, Textarea, Verdict, When, useGet, useSession } from '@tenmina/web-ui';
import { PageHead, Section, StepUpDialog, useAct, useApi, words } from '@/components/roles/kit';

type Signature = { id: string; signer_name: string; licence_number: string; licence_body: string; signed_at: string; valid: boolean };
type ReportSection = {
  id: string; number: number; label: string; key: string; title: string; owner_role: string; locked: boolean;
  in_verdict_rule: boolean; needs_signature: boolean; findings: { text?: string }; verdict: string | null;
  proposed_verdict: string | null; proposed_reasons: string[] | null; edited_at: string | null; signatures: Signature[]; can_edit: boolean;
};
type Condition = { id: string; position: number; text: string; responsible: string; closing_evidence: string; release_part: string };
type Report = {
  id: string; reference: string; case_reference: string; status: string; overall_verdict: string | null; version: number;
  sections?: ReportSection[]; conditions?: Condition[]; approvals?: { slot: string; approver: string; decision: string; at: string }[];
  allowed_verdicts?: { allowed: string[]; reasons: string[] }; released_at: string | null; pdf_sha256: string;
};

const RESPONSIBLE = ['buyer', 'seller', 'lawyer', 'surveyor', 'tenmina', 'authority', 'developer', 'other'];

export default function ReportWork() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const q = useGet<Report>(`/v1/reports/${id}`);
  const api = useApi();
  const act = useAct();
  const [approve, setApprove] = useState<null | 'approve' | 'return'>(null);
  const [note, setNote] = useState('');
  const r = q.data;
  if (q.isLoading) return <Skeleton lines={8} />;
  if (q.error || !r) return <ProblemBox error={q.error ?? 'Report not found.'} />;
  if (!r.sections) return <ProblemBox error="You are not on this case's team." />;
  const mine = (s: ReportSection) => !!me?.roles.includes(s.owner_role);
  const isLawyer = !!me?.roles.includes('LW');
  const lawyerSlot = r.approvals?.find((a) => a.slot === 'signing_lawyer');

  return (
    <div className="stack">
      <PageHead back={{ href: '/work/reports', label: 'Reports' }} label={r.case_reference} title={r.reference} />
      <div className="row"><Status value={r.status} /><Verdict value={r.overall_verdict} /><span className="muted">Version {r.version}</span></div>
      {r.status !== 'draft' ? <div className="banner-info">{r.status === 'in_review' ? 'In review. A section can change only if the review returns it.' : 'Released reports never change. A correction is a new version.'}</div> : null}

      {r.sections.filter((s) => !s.locked && s.owner_role !== 'system').map((s) => (
        <SectionCard key={s.id} report={r} s={s} mine={mine(s)} onSaved={() => q.mutate()} />
      ))}

      {isLawyer ? <Conditions report={r} onChange={() => q.mutate()} /> : null}

      {isLawyer && r.status === 'in_review' ? (
        <Section title="Your approval as signing lawyer">
          <div className="card-ink stack">
            <p style={{ margin: 0 }}>Two people approve every report: you, and a different Tenmina reviewer (RUL-03).</p>
            {lawyerSlot ? <p style={{ margin: 0 }}>You chose <strong>{lawyerSlot.decision}</strong> on <When value={lawyerSlot.at} withTime />.</p> : (
              <>
                <Field label="Note (needed to return it)"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
                <div className="row">
                  <Button variant="primary" onClick={() => setApprove('approve')}>Approve for release</Button>
                  <Button variant="ghost" style={{ color: '#fff' }} onClick={() => setApprove('return')} disabled={!note.trim()}>Return with note</Button>
                </div>
              </>
            )}
          </div>
        </Section>
      ) : null}
      <ProblemBox error={act.error} />
      <StepUpDialog open={!!approve} onClose={() => setApprove(null)} title={approve === 'return' ? 'Return the report' : 'Approve the report'}
        onConfirmed={async () => { await api('POST', `/v1/reports/${id}/approvals`, { decision: approve, note }); await q.mutate(); act.show(approve === 'return' ? 'Returned.' : 'Approved.'); }}>
        <p className="muted">Enter your code to confirm. It is recorded with your name and the time.</p>
      </StepUpDialog>
      {act.toast}
    </div>
  );
}

function SectionCard({ report, s, mine, onSaved }: { report: Report; s: ReportSection; mine: boolean; onSaved: () => void }) {
  const api = useApi();
  const act = useAct();
  const [text, setText] = useState(s.findings?.text ?? '');
  const [verdict, setVerdict] = useState(s.verdict ?? '');
  const [sign, setSign] = useState(false);
  const editable = mine && s.can_edit && report.status === 'draft';
  const valid = s.signatures.find((g) => g.valid);
  const dirty = text !== (s.findings?.text ?? '') || verdict !== (s.verdict ?? '');
  return (
    <Card className="stack">
      <div className="spread">
        <div><div className="label">Section {s.label} · {words(s.owner_role === 'LW' ? 'lawyer' : s.owner_role === 'SV' ? 'surveyor' : s.owner_role === 'CM' ? 'case manager' : s.owner_role)}</div><h3 style={{ margin: 0 }}>{s.title || words(s.key)}</h3></div>
        {s.in_verdict_rule ? <Verdict value={s.verdict} /> : null}
      </div>
      {s.proposed_verdict && editable ? <p className="muted" style={{ margin: 0 }}>Proposed from the checks: {words(s.proposed_verdict)}{s.proposed_reasons?.length ? `. ${s.proposed_reasons.join(' ')}` : ''}</p> : null}
      {editable ? (
        <>
          <Field label="Findings"><Textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} /></Field>
          {s.in_verdict_rule ? (
            <Field label="Section verdict">
              <div className="seg" role="group" aria-label="Section verdict">
                {['green', 'amber', 'red'].map((v) => <button key={v} type="button" aria-pressed={verdict === v} onClick={() => setVerdict(v)}>{v === 'green' ? '✓ Green' : v === 'amber' ? '! Amber' : '✕ Red'}</button>)}
              </div>
            </Field>
          ) : null}
          <Button variant="dark" disabled={!dirty} busy={act.busy === 'save'} onClick={() => act.run('save', async () => {
            await api('PUT', `/v1/reports/${report.id}/sections/${s.number}`, { findings: { ...s.findings, text }, ...(s.in_verdict_rule && verdict ? { verdict } : {}) });
            onSaved();
          }, 'Saved. Any earlier signature on this section is no longer valid.')}>Save section</Button>
        </>
      ) : <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.findings?.text || <span className="muted">Not filled yet.</span>}</p>}
      {s.needs_signature ? (
        valid ? (
          <div className="row"><Chip tone="lime">✓ Signed</Chip><span style={{ fontSize: 14 }}>{valid.signer_name}, licence <span className="mono">{valid.licence_number}</span> ({valid.licence_body}), <When value={valid.signed_at} withTime /></span></div>
        ) : editable ? (
          <Button variant="primary" disabled={dirty || !text.trim()} onClick={() => setSign(true)}>Sign this section</Button>
        ) : <span className="muted" style={{ fontSize: 14 }}>Not signed yet.</span>
      ) : null}
      <ProblemBox error={act.error} />
      <StepUpDialog open={sign} onClose={() => setSign(false)} title={`Sign section ${s.label}`}
        onConfirmed={async () => { await api('POST', `/v1/reports/${report.id}/sections/${s.number}/signatures`); onSaved(); act.show('Signed with your name, licence number and the time.'); }}>
        <KV items={[['Section', `${s.label}. ${s.title || words(s.key)}`], ['Verdict', s.in_verdict_rule ? <Verdict key="v" value={s.verdict} /> : 'No verdict in this section']]} />
        <p className="muted">Your signature records your name, licence number and the time. Saving the section later makes it invalid.</p>
      </StepUpDialog>
      {act.toast}
    </Card>
  );
}

function Conditions({ report, onChange }: { report: Report; onChange: () => void }) {
  const api = useApi();
  const act = useAct();
  const [text, setText] = useState('');
  const [resp, setResp] = useState('seller');
  const [closing, setClosing] = useState('');
  const editable = report.status === 'draft';
  return (
    <Section title="Section 11: release conditions">
      <p className="muted" style={{ margin: 0 }}>Each condition is copied into the escrow. Say who must act and what evidence closes it.</p>
      {(report.conditions ?? []).map((c) => (
        <Card key={c.id} className="spread">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="label">{c.position}. {words(c.responsible)} · {words(c.release_part)} release</div>
            <div style={{ fontWeight: 700 }}>{c.text}</div>
            <div className="muted" style={{ fontSize: 14 }}>Closed by: {c.closing_evidence}</div>
          </div>
          {editable ? <Button size="sm" variant="ghost" busy={act.busy === c.id} onClick={() => act.run(c.id, async () => { await api('DELETE', `/v1/reports/${report.id}/conditions/${c.id}`); onChange(); }, 'Removed.')}>Remove</Button> : null}
        </Card>
      ))}
      {!(report.conditions ?? []).length ? <p className="muted">No conditions yet.</p> : null}
      {editable ? (
        <Card className="stack">
          <Field label="Condition"><Input value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <Field label="Who must act"><Select value={resp} onChange={(e) => setResp(e.target.value)}>{RESPONSIBLE.map((x) => <option key={x} value={x}>{words(x)}</option>)}</Select></Field>
          <Field label="Evidence that closes it"><Input value={closing} onChange={(e) => setClosing(e.target.value)} /></Field>
          <Button variant="dark" disabled={!text.trim() || !closing.trim()} busy={act.busy === 'add'} onClick={() => act.run('add', async () => {
            await api('POST', `/v1/reports/${report.id}/conditions`, { text, responsible: resp, closing_evidence: closing });
            setText(''); setClosing(''); onChange();
          }, 'Condition added.')}>Add condition</Button>
        </Card>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Section>
  );
}
