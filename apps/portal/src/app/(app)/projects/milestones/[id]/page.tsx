'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, Chip, KV, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { ApproveMoney, EvidenceLink, Ink, PageHead, Proof, Section, list, useAction, words, type Any } from '@/components/kit';

/** W-20 · SCR-PTL-23: milestone approval with local-currency re-pricing (RUL-18), defects held back (RUL-09). */
export default function Milestone() {
  const { id } = useParams<{ id: string }>();
  const m = useGet<Any>(`/v1/milestones/${id}`);
  const rp = useGet<Any[]>(`/v1/milestones/${id}/reprices`);
  const insp = useGet<Any>(`/v1/milestones/${id}/inspections`, undefined, { shouldRetryOnError: false });
  const pays = useGet<Any>('/v1/project-payments');
  const ev = useGet<Any>('/v1/evidence', { subject_type: 'milestone', subject_id: id });
  const defects = useGet<Any>('/v1/defects');
  const a = useAction();
  if (m.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!m.data) return <Ink><ProblemBox error={m.error} /></Ink>;
  const ms = m.data;
  const pay = list(pays.data).find((p: Any) => p.milestone_id === id && p.status === 'awaiting_client') ?? list(pays.data).find((p: Any) => p.milestone_id === id);
  const reprice = (rp.data ?? [])[0] ?? pay?.reprice;
  const myDefects = list(defects.data).filter((d: Any) => d.milestone_id === id);
  const inspections = list(insp.data);
  const refresh = () => { m.mutate(); pays.mutate(); rp.mutate(); };
  return (
    <Ink>
      <PageHead back={{ href: `/projects/${ms.project_id}`, label: 'The project' }} label={`Milestone ${ms.seq} · ${words(ms.status)}`} title={ms.name} sub={ms.waiting_reason} />
      {ms.fraud_flagged || ms.freeze_kind ? <Blocked title="Payment held">{ms.freeze_kind ? words(ms.freeze_kind) : 'A check on the evidence is open.'}</Blocked> : null}
      <Section title="Evidence from the site">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          {(ms.required_evidence ?? []).map((r: Any) => <div key={r.key} className="check-row"><span className={`tick ${ms.evidence_checked_at ? 'done' : ''}`}>{ms.evidence_checked_at ? '✓' : ''}</span><div>{r.label}<div className="muted" style={{ fontSize: 13 }}>{words(r.media)}, taken in Tenmina Field</div></div><span /></div>)}
          {ms.evidence_checked_at ? <div className="check-row"><span className="tick done">✓</span><div>Checked by Tenmina <When value={ms.evidence_checked_at} /></div><span /></div> : null}
        </div>
        <div className="row">{list(ev.data).slice(0, 8).map((e: Any) => <EvidenceLink key={e.id} id={e.id} label={words(e.role) || 'Photo'} variant="preview" />)}</div>
      </Section>
      <Section title="Inspection">
        {inspections.length ? inspections.map((i: Any) => (
          <div key={i.id} className="card"><div className="spread"><strong>{i.inspector_name ?? i.inspector ?? 'Inspector'}</strong><Chip>{words(i.outcome || i.status)}</Chip></div>{i.recorded_at ? <div className="muted"><When value={i.recorded_at} withTime /></div> : null}{i.notes ? <p style={{ margin: '6px 0 0' }}>{i.notes}</p> : null}</div>
        )) : ms.inspected_at ? <Proof>Inspected <When value={ms.inspected_at} /></Proof> : <p className="muted" style={{ margin: 0 }}>Not inspected yet. Every stage is inspected before it is paid.</p>}
      </Section>
      {myDefects.length ? (
        <Section title="Defects held back">
          {myDefects.map((d: Any) => <div key={d.id} className="card spread"><span>{d.description}<div className="muted" style={{ fontSize: 13 }}>{words(d.status)}</div></span><Money value={d.value} /></div>)}
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Their value stays at the bank until the inspector confirms the fix.</p>
        </Section>
      ) : null}
      {reprice ? (
        <Section title="Price in local currency">
          <KV items={[
            ['Agreed guide', <Money key="g" value={reprice.guide} />],
            ['Rate', `${reprice.rate} on ${reprice.rate_date}`],
            ['Amount now', <Money key="a" value={reprice.amount} />],
            ['Before', <Money key="p" value={reprice.previous} />],
          ]} />
          {reprice.changed ? <div className="card">The local amount changed since the plan. You confirm the new amount when you approve.</div> : null}
        </Section>
      ) : null}
      {pay && pay.status === 'awaiting_client' ? (
        <ApproveMoney amount={pay.amount} payee={pay.payee?.account_name ?? pay.payee?.name}
          above={Number(pay.holdback?.amount) > 0 ? <div style={{ color: '#6a675f', fontSize: 14 }}>Less defects held back: <Money value={pay.holdback} /></div> : null}
          payeeLines={<div className="mono" style={{ fontSize: 14 }}>{pay.payee?.bank_name} · account ending {pay.payee?.account_last4}{pay.payee?.verified ? ' · verified' : ''}</div>}
          onApprove={(code) => a.post(`/v1/project-payments/${pay.id}/client-approval`, { confirm_amount: reprice?.changed ? reprice.amount : undefined, code }).then(() => { refresh(); a.show('Approved. Two Tenmina staff approve next.'); })}
          onDecline={(reason) => a.post(`/v1/project-payments/${pay.id}/client-decline`, { reason }).then(() => { refresh(); a.show('Declined. Nothing is paid.'); })}
          declineLabel="Do not pay this stage"
          note={<p className="muted" style={{ margin: 0, fontSize: 14 }}>{pay.route === 'escrow' ? 'The bank pays from the project money it holds, after two Tenmina staff approve.' : 'After two Tenmina staff confirm, you pay the verified payee yourself.'}</p>} />
      ) : pay ? <Link href={`/projects/payments/${pay.id}`} className="btn btn-ghost">The payment · {words(pay.status)}</Link> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
