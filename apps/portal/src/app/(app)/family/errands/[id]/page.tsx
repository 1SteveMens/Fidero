'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, KV, Money, NeedsYou, ProblemBox, Skeleton, Steps, Textarea, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, EvidenceLink, FilePick, PageHead, Proof, Section, StepUpButton, money, postForm, useAction, useCountry, words, type Any } from '@/components/kit';

/** W-34 · SCR-PTL-50: errand checklist and progress, step fees approved one by one or under a standing approval. */
export default function Errand() {
  const { id } = useParams<{ id: string }>();
  const country = useCountry();
  const q = useGet<Any>(`/v1/errands/${id}`);
  const pay = useGet<Any>(`/v1/errands/${id}/payments`);
  const terms = useGet<Any>(q.data?.status === 'draft' || q.data?.status === 'documents_pending' ? '/v1/catalogue/terms' : null, { country: country.code });
  const a = useAction();
  const [sa, setSa] = useState(false);
  const [max, setMax] = useState('');
  const [code, setCode] = useState('');
  const [cancel, setCancel] = useState(false);
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const e = q.data;
  const refresh = () => { q.mutate(); pay.mutate(); };
  const blockers = pay.data?.blocking_reasons ?? e.blocking_reasons ?? [];
  const notSubmitted = !e.submitted_at;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={`${e.reference} · ${words(e.status)}`} title={e.name} sub={e.status_text} />
      {(e.steps ?? []).filter((s: Any) => s.release_instruction_id && s.status === 'fee_instructed' && !s.paid_at).map((s: Any) => <NeedsYou key={s.id} title={`Step ${s.seq} fee: ${s.description}`} detail="Open it to see whether it waits for your approval. Nothing is paid until you approve." href={`/property/releases/${s.release_instruction_id}`} />)}
      {e.agency_payee && !e.agency_approved_at ? (
        <section className="needs-you" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div><div className="label" style={{ color: '#0b0b0b' }}>Needs you</div><strong>Agree {e.agency_payee.legal_name} (account ending {e.agency_payee.last4}) as the payee</strong></div>
          <StepUpButton label="Agree the payee" variant="dark" onRun={() => a.post(`/v1/errands/${id}/agency-approvals`).then(refresh)} />
        </section>
      ) : null}
      <KV items={[['For', e.for_family_member ? e.for_family_member.full_name ?? 'Family member' : 'You'], ['Agent', e.agent?.name ?? 'Not assigned yet'], ['Target', e.due_on ? <When key="d" value={e.due_on} /> : `${e.target_days ?? '—'} days`]]} />
      <Section title="Documents">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          {(e.documents ?? []).map((d: Any) => (
            <div key={d.key} className="check-row">
              <span className={`tick ${d.status === 'accepted' ? 'done' : ''}`}>{d.status === 'accepted' ? '✓' : d.status === 'rejected' ? '✕' : ''}</span>
              <div>{d.label}{d.required ? '' : ' (optional)'}<div className="muted" style={{ fontSize: 13 }}>{d.status === 'rejected' ? `Not accepted: ${d.reject_reason}` : words(d.status)}</div></div>
              {d.status !== 'accepted' ? <FilePick label={d.evidence ? 'Replace' : 'Upload'} busy={a.busy === d.key} onFile={(f) => { const fd = new FormData(); fd.append('file', f); a.run(d.key, () => postForm(`/v1/errands/${id}/documents/${d.key}`, fd), 'Stored', refresh); }} /> : <span />}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Payments">
        {pay.data ? (
          <div className="stack">
            <div className="card stack" style={{ gap: 4 }}>
              <div className="spread"><strong>Tenmina&apos;s charge</strong><Money value={money(pay.data.tenmina_charge.amount, pay.data.tenmina_charge.currency)} /></div>
              <span className="muted" style={{ fontSize: 14 }}>{pay.data.tenmina_charge.note}</span>
              {pay.data.tenmina_charge.paid ? <Proof>Paid</Proof> : e.fee_order_id ? <Link className="btn btn-primary btn-sm" href={`/property/orders/${e.fee_order_id}`}>Pay the charge</Link> : <span className="muted" style={{ fontSize: 14 }}>You can pay it once you submit.</span>}
            </div>
            <div className="card stack" style={{ gap: 4 }}>
              <div className="spread"><strong>Official fees</strong><Money value={money(pay.data.official_fees.amount, pay.data.official_fees.currency)} /></div>
              <span className="muted" style={{ fontSize: 14 }}>{pay.data.official_fees.note}</span>
              <Link className="btn btn-ghost btn-sm" href="/family/held-funds">Add money at the bank</Link>
            </div>
          </div>
        ) : <Skeleton />}
        {blockers.length ? <div className="card"><strong>Before an agent can start</strong><ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{blockers.map((b: Any, i: number) => <li key={i}>{b.message}</li>)}</ul></div> : null}
        {notSubmitted ? (
          <Button variant="primary" busy={a.busy === 'sub'} onClick={() => a.run('sub', () => a.post(`/v1/errands/${id}/submit`, { terms_version: terms.data?.terms_version, scope_version: terms.data?.scope_version }), 'Submitted', refresh)}>Agree to the terms and submit</Button>
        ) : null}
      </Section>
      <Section title="Steps">
        <Steps items={(e.steps ?? []).map((s: Any) => ({ label: `${s.seq}. ${s.description}`, state: s.status === 'done' ? 'done' : ['in_progress', 'fee_instructed', 'fee_paid', 'receipted'].includes(s.status) ? 'now' : 'next', detail: [s.plain, Number(s.official_fee?.amount) > 0 ? `Fee ${s.official_fee.currency} ${s.official_fee.amount}` : ''].filter(Boolean).join(' · ') }))} />
        <div className="row">{(e.steps ?? []).flatMap((s: Any) => [s.acknowledgement_evidence && <EvidenceLink key={`a${s.id}`} id={s.acknowledgement_evidence} label={`Step ${s.seq} acknowledgement`} variant="preview" />, s.receipt_evidence && <EvidenceLink key={`r${s.id}`} id={s.receipt_evidence} label={`Step ${s.seq} receipt`} variant="preview" />]).filter(Boolean)}</div>
        <div className="card stack">
          {e.standing_approval?.status === 'active' ? (
            <><Proof>Step fees approved up to <Money value={money(e.standing_approval.monthly_max, e.standing_approval.currency)} /> a month</Proof>
              <Button variant="ghost" size="sm" busy={a.busy === 'w'} onClick={() => a.run('w', () => a.post(`/v1/errands/${id}/standing-approvals`, undefined, 'DELETE'), 'Withdrawn', refresh)}>Withdraw</Button></>
          ) : <><span>Each step fee waits for your approval. You can approve them up to a monthly amount instead.</span><Button variant="ghost" onClick={() => setSa(true)}>Give a standing approval</Button></>}
        </div>
      </Section>
      {e.result_evidence ? (
        <Section title="The result">
          <div className="card stack"><Proof>Checked <When value={e.result_checked_at} /></Proof>{e.result_note ? <span>{e.result_note}</span> : null}<EvidenceLink id={e.result_evidence} label="See the document" variant="preview" /></div>
        </Section>
      ) : null}
      {e.handover ? (
        <Section title="Handover">
          <div className="card stack">
            <span>{words(e.handover.method)} to {e.handover.receiver_name}{e.handover.tracking_reference ? ` · tracking ${e.handover.tracking_reference}` : ''} on <When value={e.handover.handed_at} withTime /></span>
            {e.handover.evidence ? <EvidenceLink id={e.handover.evidence} label="Proof of handover" variant="preview" /> : null}
            {e.handover.confirmed_at ? <Proof>You confirmed receipt <When value={e.handover.confirmed_at} /></Proof> : <Button variant="primary" busy={a.busy === 'h'} onClick={() => a.run('h', () => a.post(`/v1/errands/${id}/handover-confirmations`), 'Thank you', refresh)}>I have received it</Button>}
          </div>
        </Section>
      ) : null}
      <ProblemBox error={a.error} />
      {!['handed_over', 'completed', 'cancelled'].includes(e.status) ? <Button variant="ghost" onClick={() => setCancel(true)}>Cancel the errand</Button> : null}
      <ActionDialog ink open={sa} onClose={() => setSa(false)} title="Standing approval for step fees" submit="Give the approval" busy={a.busy === 'sa'} error={a.error} disabled={!max || code.length !== 6}
        onSubmit={() => a.run('sa', () => a.post(`/v1/errands/${id}/standing-approvals`, { monthly_max: max, code }), 'Standing approval given', () => { setSa(false); refresh(); })}>
        <Field label={`Up to this much a month (${pay.data?.official_fees?.currency ?? country.currency})`}><Input inputMode="decimal" value={max} onChange={(ev) => setMax(ev.target.value.replace(/[^\d.]/g, ''))} /></Field>
        <Field label="Code from your authenticator app"><Input inputMode="numeric" maxLength={6} value={code} onChange={(ev) => setCode(ev.target.value.replace(/\D/g, ''))} /></Field>
      </ActionDialog>
      <ActionDialog open={cancel} onClose={() => setCancel(false)} title="Cancel the errand" submit="Cancel" busy={a.busy === 'c'} error={a.error}
        onSubmit={() => a.run('c', () => a.post(`/v1/errands/${id}/cancel`, { reason }), 'Cancelled', () => { setCancel(false); refresh(); })}>
        <Field label="Why"><Textarea value={reason} onChange={(ev) => setReason(ev.target.value)} required /></Field>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
