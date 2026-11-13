'use client';
/* Report builder · SCR-BO-08 · W-14, with review and release (SCR-BO-09). Sections 1 to 14 with verdicts in icon
 * and word, the verdict rule (RUL-02), the locked scope text (RUL-04), signatures with licence (RUL-20), conditions
 * as structured items, submit for review, the two-person release (RUL-03), the PDF and its hash, corrections. */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Blocked, Button, call, Empty, Field, ProblemBox, Skeleton, Textarea, useGet, useSession, Verdict } from '@tenmina/web-ui';
import { ActionForm, dayTime, DoneSlot, Head, MySlot, OpenSlot, Panel, useAct, words } from '@/components/core/kit';
import { uploadEvidence } from '@/components/core/upload';
import type { Reason, ReportDetail, Section } from '@/components/core/types';

const VERDICTS = ['green', 'amber', 'red'] as const;
const MEANS: Record<string, string> = { green: 'No issue found that affects the purchase.', amber: 'Proceed only once the conditions are met.', red: 'Do not proceed.' };
const RESPONSIBLE = ['buyer', 'seller', 'lawyer', 'surveyor', 'tenmina', 'authority', 'developer', 'other'];

function reasonText(r: string | Reason): string { return typeof r === 'string' ? r : `${r.rule ? r.rule + ': ' : ''}${r.message}`; }

function SectionEditor({ r, s, reload }: { r: ReportDetail; s: Section; reload: () => void }) {
  const { client, stepUp } = useSession();
  const [text, setText] = useState(String(s.findings?.text ?? ''));
  const [verdict, setVerdict] = useState<string | null>(s.verdict);
  const [file, setFile] = useState<File | null>(null);
  const [code, setCode] = useState('');
  const act = useAct();
  useEffect(() => { setText(String(s.findings?.text ?? '')); setVerdict(s.verdict); }, [s.id, s.findings, s.verdict]);
  const others = Object.entries(s.findings ?? {}).filter(([k]) => k !== 'text');
  const draft = r.status === 'draft';
  async function save() {
    const ok = await act.run(async () => {
      const ids = file ? [await uploadEvidence(client, file, { subject_type: 'report', subject_id: r.id, role: `section_${s.number}` })] : [];
      return call(client, 'PATCH', `/v1/reports/${r.id}/sections/${s.number}`, { findings: { ...(s.findings ?? {}), text }, verdict, evidence_ids: ids });
    }, `Section ${s.number} saved.`);
    if (ok !== undefined) { setFile(null); reload(); }
  }
  async function sign() {
    const ok = await act.run(async () => { await stepUp(code); return call(client, 'POST', `/v1/reports/${r.id}/sections/${s.number}/signatures`); }, 'Signed.');
    if (ok !== undefined) { setCode(''); reload(); }
  }
  const validSig = s.signatures.find((g) => g.valid);
  return (
    <Panel title={`${s.number}. ${s.title}`} actions={<span className="chip">Owner {s.owner_role === 'system' ? 'system' : s.owner_role}</span>}>
      {s.locked ? (
        <>
          <div className="strip-ink"><span aria-hidden>🔒</span>Locked text{r.scope_version ? ` v${r.scope_version}` : ''}. It cannot be edited here. Changes go through admin with two approvals (RUL-04).</div>
          {s.findings?.text ? <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{String(s.findings.text)}</p> : <p className="muted" style={{ margin: 0 }}>Filled in when the report is sent for review.</p>}
        </>
      ) : (
        <>
          {others.length ? <dl className="facts">{others.map(([k, v]) => <div key={k}><dt>{words(k)}</dt><dd>{typeof v === 'string' ? v : JSON.stringify(v)}</dd></div>)}</dl> : null}
          <Field label="Findings"><Textarea value={text} onChange={(e) => setText(e.target.value)} disabled={!s.can_edit} style={{ minHeight: 140 }} /></Field>
          {s.in_verdict_rule || s.verdict || s.proposed_verdict ? (
            <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="stack">
              <legend className="label">Section verdict</legend>
              {s.proposed_verdict ? <div className="row" style={{ gap: 8, fontSize: 14 }}>Proposed by the overlay checks: <Verdict value={s.proposed_verdict} /></div> : null}
              <div className="row" style={{ gap: 8 }}>
                {VERDICTS.map((v) => (
                  <label key={v} className="row" style={{ gap: 6, minHeight: 44, cursor: s.can_edit ? 'pointer' : 'default' }}>
                    <input type="radio" name={`v-${s.id}`} checked={verdict === v} onChange={() => setVerdict(v)} disabled={!s.can_edit} style={{ width: 20, height: 20 }} />
                    <Verdict value={v} />
                  </label>
                ))}
              </div>
              {verdict ? <div className="muted" style={{ fontSize: 14 }}>{words(verdict)} means: {MEANS[verdict]}</div> : null}
            </fieldset>
          ) : null}
          {s.can_edit ? (
            <Field label="Attach evidence from the case" hint="Fingerprinted and stored; it cannot be changed afterwards.">
              <input className="input" type="file" accept="image/*,application/pdf,video/mp4" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Field>
          ) : draft ? <p className="muted" style={{ margin: 0, fontSize: 14 }}>Only the section owner ({s.owner_role}) edits this section.</p> : null}
          {s.edited_at ? <div className="mono muted" style={{ fontSize: 12 }}>Last saved {dayTime(s.edited_at)}</div> : null}
          {s.can_edit ? <div><Button variant="dark" onClick={save} busy={act.busy}>Save section</Button></div> : null}
        </>
      )}
      {s.needs_signature ? (
        <div className="stack" style={{ borderTop: '1px solid var(--color-line)', paddingTop: 12 }}>
          <div className="label">Signature</div>
          {s.signatures.length ? s.signatures.map((g) => (
            <div key={g.id} className="row" style={{ gap: 8 }}>
              <span className={g.valid ? 'gate-mark' : 'gate-mark gate-no'} aria-hidden>{g.valid ? '✓' : '✕'}</span>
              <span><strong>{g.signer_name}</strong> · licence <span className="mono">{g.licence_number}</span> ({g.licence_body}) · <span className="mono">{dayTime(g.signed_at)}</span>{g.invalidated_at ? ` · no longer valid: ${g.invalidated_reason}` : ''}</span>
            </div>
          )) : <p className="muted" style={{ margin: 0 }}>Not signed yet.</p>}
          {draft && s.can_edit && !validSig ? (
            <div className="stack">
              <Field label="Code from your authenticator app to sign">
                <input className="input" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} style={{ maxWidth: 180, fontFamily: 'var(--font-mono)' }} />
              </Field>
              <div><Button variant="primary" onClick={sign} busy={act.busy} disabled={code.length !== 6}>Sign section {s.number}</Button></div>
              <p className="muted" style={{ margin: 0, fontSize: 13 }}>Your name, licence number and the time are recorded. Your licence must be valid today (RUL-20).</p>
            </div>
          ) : null}
        </div>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Panel>
  );
}

export default function ReportBuilder() {
  const { id } = useParams<{ id: string }>();
  const { client, me } = useSession();
  const rep = useGet<ReportDetail>(`/v1/reports/${id}`);
  const [num, setNum] = useState<number | null>(null);
  const act = useAct();
  if (rep.isLoading) return <Skeleton lines={8} />;
  if (!rep.data) return <ProblemBox error={rep.error ?? 'Report not found.'} />;
  const r = rep.data;
  if (!r.sections) {
    return (
      <div className="stack"><Head crumb={{ href: '/reports', label: 'Reports' }} title={r.reference} chips={<Verdict value={r.overall_verdict} />} />
        <p>You can see the released report only.</p></div>
    );
  }
  const reload = () => rep.mutate();
  const current = r.sections.find((s) => s.number === (num ?? r.sections.find((x) => x.can_edit)?.number ?? 1)) ?? r.sections[0];
  const sigNeeded = r.sections.filter((s) => s.needs_signature);
  const sigDone = sigNeeded.filter((s) => s.signatures.some((g) => g.valid));
  const draft = r.status === 'draft';
  const allowed = r.allowed_verdicts?.allowed ?? [];
  const iApproved = r.approvals.some((a) => a.approver === me?.id);

  async function setOverall(v: string) {
    await act.run(() => call(client, 'POST', `/v1/reports/${id}/verdict`, { overall_verdict: v }).then(reload), `Overall verdict set to ${v}.`);
  }
  async function pdf() {
    const out = await act.run(() => call<{ url: string; sha256: string }>(client, 'GET', `/v1/reports/${id}/pdf`));
    if (out?.url) window.open(out.url, '_blank', 'noopener');
  }

  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/reports', label: 'Reports' }} title={<><span className="mono" style={{ fontSize: '0.55em', display: 'block' }}>{r.reference} · v{r.version}</span>Report builder</>}
        chips={<><span className="chip">Template v{r.template_version_number}</span><span className="chip">{words(r.status)}</span><Verdict value={r.overall_verdict} /><span className="chip">Signatures {sigDone.length} of {sigNeeded.length}</span></>}
        sub={<>Case <Link href={`/cases/${r.case}`}>{r.case_reference}</Link>{r.supersedes ? <> · corrects an earlier version: {r.correction_reason}</> : null}</>}
        actions={<>
          {r.pdf_sha256 ? <Button variant="ghost" size="sm" onClick={pdf}>Open PDF</Button> : null}
          {draft ? <Button variant="primary" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/reports/${id}/submit-review`).then(reload), 'Sent for review.')}>Send for review</Button> : null}
        </>} />
      <ProblemBox error={act.error} />
      {r.release_error ? <Blocked title="Release blocked">{r.release_error}</Blocked> : null}

      <div className="cols cols-side">
        <div className="stack">
          <Panel title="Sections">
            <div className="sec-list" role="list">
              {r.sections.map((s) => (
                <button key={s.id} type="button" className="sec-btn" aria-current={s.number === current.number} onClick={() => setNum(s.number)} role="listitem">
                  <span>{s.number} {s.title}</span>
                  <span className="row" style={{ gap: 6 }}>
                    {s.locked ? <span aria-label="locked">🔒</span> : null}
                    {s.verdict ? <Verdict value={s.verdict} /> : s.needs_signature ? <span className="mono" style={{ fontSize: 11 }}>{s.signatures.some((g) => g.valid) ? '✓ signed' : '—'}</span> : <span className="mono" style={{ fontSize: 11 }}>auto</span>}
                  </span>
                </button>
              ))}
            </div>
          </Panel>
        </div>
        <SectionEditor key={current.id} r={r} s={current} reload={reload} />
      </div>

      <div className="grid2">
        <Panel title="Overall verdict">
          <div className="row" style={{ gap: 8 }}>Now: <Verdict value={r.overall_verdict} /></div>
          <div className="muted" style={{ fontSize: 14 }}>Allowed: {allowed.length ? allowed.map(words).join(', ') : 'none yet'}</div>
          {(r.allowed_verdicts?.reasons ?? []).map((x, i) => <div key={i} style={{ fontWeight: 700 }}>{reasonText(x)}</div>)}
          {draft ? (
            <div className="row" style={{ gap: 8 }}>
              {VERDICTS.map((v) => (
                <Button key={v} size="sm" variant={r.overall_verdict === v ? 'dark' : 'ghost'} disabled={!allowed.includes(v) || act.busy} onClick={() => setOverall(v)} title={!allowed.includes(v) ? `Overall cannot be ${v} (RUL-02).` : undefined}>Set {words(v)}</Button>
              ))}
            </div>
          ) : null}
          {draft && !allowed.includes('green') ? <p style={{ margin: 0, fontSize: 14 }}>Overall cannot be green while any section from 4 to 10 is red (RUL-02).</p> : null}
        </Panel>
        <Panel title="Conditions (copied to the escrow)" actions={draft ? (
          <ActionForm label="+ Add condition" path={`/v1/reports/${id}/conditions`} fields={[
            { name: 'text', label: 'Condition', type: 'textarea', required: true },
            { name: 'responsible', label: 'Who must meet it', type: 'select', required: true, options: RESPONSIBLE.map((x) => ({ value: x, label: words(x) })) },
            { name: 'closing_evidence', label: 'Evidence that closes it', required: true },
            { name: 'key', label: 'Short key (optional)' },
          ]} onDone={reload} submitLabel="Add condition" />
        ) : null}>
          {r.conditions.length ? (
            <div className="rows">
              {r.conditions.map((c) => (
                <div key={c.id} className="rowlink">
                  <div className="main"><div className="title">{c.position}. {c.text}</div><div className="meta">{words(c.responsible)} · evidence: {c.closing_evidence}{c.release_part !== 'main' ? ' · held-back share' : ''}</div></div>
                  {draft ? <Button size="sm" variant="ghost" onClick={() => act.run(() => call(client, 'DELETE', `/v1/reports/${id}/conditions/${c.id}`).then(reload), 'Condition removed.')}>Remove</Button> : null}
                </div>
              ))}
            </div>
          ) : <Empty>No conditions.</Empty>}
        </Panel>
      </div>

      {r.status !== 'draft' ? (
        <section className="card-ink stack" aria-label="Review and release">
          <h2 style={{ margin: 0, fontSize: 18 }}>Review and release</h2>
          <p style={{ margin: 0, opacity: 0.85 }}>The signing lawyer and a different Tenmina reviewer both approve (RUL-03). Release also waits for every party&apos;s identity check and an official record for every search.</p>
          <div className="grid2">
            {[0, 1].map((i) => {
              const a = r.approvals[i];
              const title = `Approval ${i + 1} of 2`;
              if (a) return <DoneSlot key={i} title={title} name={words(a.slot)} at={a.at} decision={a.decision} />;
              if (r.status === 'in_review' && i === r.approvals.length && !iApproved) {
                return <MySlot key={i} title={title} confirmText="I read every section and checked the evidence myself" holdLabel="Press and hold to approve"
                  onApprove={async () => { await call(client, 'POST', `/v1/reports/${id}/approvals`, { decision: 'approve' }); await reload(); }}
                  onReturn={async (note) => { await call(client, 'POST', `/v1/reports/${id}/approvals`, { decision: 'return', note }); await reload(); }} />;
              }
              return <OpenSlot key={i} title={title} text={iApproved ? 'You gave an approval. A different person gives this one (RUL-03).' : r.status === 'in_review' ? 'Waiting' : '—'} />;
            })}
          </div>
          {r.status === 'approved' ? <div><Button variant="primary" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/reports/${id}/release`).then(reload), 'Released.')}>Try the release again</Button></div> : null}
          {r.pdf_sha256 ? (
            <div className="stack" style={{ gap: 4 }}>
              <div className="label" style={{ color: '#a9a69e' }}>PDF fingerprint (SHA-256)</div>
              <div className="mono" style={{ overflowWrap: 'anywhere', fontSize: 13 }}>{r.pdf_sha256}</div>
              <div className="mono" style={{ fontSize: 12, opacity: 0.8 }}>Released {dayTime(r.released_at)}</div>
            </div>
          ) : null}
          {r.status === 'released' ? (
            <div className="row">
              <ActionForm label="Issue a correction" variant="primary" path={`/v1/reports/${id}/corrections`} fields={[{ name: 'reason', label: 'What is corrected and why', type: 'textarea', required: true }, { name: 'incident_id', label: 'Re-check incident (if any)' }]}
                body={(v) => ({ reason: v.reason, ...(v.incident_id ? { incident_id: v.incident_id } : {}) })} onDone={(out) => { const n = out as { id?: string }; if (n?.id) window.location.href = `/reports/${n.id}`; }} submitLabel="Start new version" intro="A released report never changes. A correction is a new version; the client is told." />
              <ActionForm label="Make an anonymised copy" path={`/v1/reports/${id}/anonymised-copies`} onDone={() => act.show('Anonymised copy made.')} submitLabel="Make copy" intro="Only with the client's written consent on file (FR-RPT-011)." />
            </div>
          ) : null}
        </section>
      ) : null}
      {act.toast}
    </div>
  );
}
