'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Chip, KV, Money, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { ApproveMoney, EvidenceLink, Ink, PageHead, Proof, RadioCard, Section, useAction, words, type Any } from '@/components/kit';

/** W-33 · SCR-PTL-48: two or more quotes from vetted contractors; approve one; money held; inspection; payment. */
export default function Repair() {
  const { id } = useParams<{ id: string }>();
  const { stepUp } = useSession();
  const q = useGet<Any>(`/v1/repairs/${id}`);
  const a = useAction();
  const [pick, setPick] = useState('');
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const r = q.data;
  const quotes = (r.quotes ?? []).filter((x: Any) => x.status !== 'withdrawn');
  const chosen = quotes.find((x: Any) => x.id === pick);
  const choosing = r.status === 'quotes_ready' && !r.approved_quote;
  return (
    <Ink>
      <PageHead back={{ href: `/projects/properties/${r.property}`, label: r.property_title }} label={`Repair · ${words(r.status)}${r.urgent ? ' · urgent' : ''}`} title={r.title} sub={r.description} />
      <p className="muted" style={{ margin: 0 }}>Reported by {r.reported_by?.name} ({words(r.reporter_role)}) on <When value={r.created_at} />.</p>
      {(r.approval_blockers ?? []).length ? <Blocked title="Not ready to approve">{r.approval_blockers.map((b: Any) => b.message).join(' ')}</Blocked> : null}
      <Section title={`Quotes (${quotes.length} of ${r.quotes_needed} needed)`}>
        {quotes.map((x: Any) => (
          <RadioCard key={x.id} name="quote" checked={pick === x.id || r.approved_quote === x.id} onChange={() => choosing && setPick(x.id)}>
            <div className="spread"><strong>{x.contractor?.name}</strong><Money value={x.amount} /></div>
            <div className="muted" style={{ fontSize: 14 }}>{x.track_record ? `${x.track_record.completed} jobs done · ${x.track_record.disputes} disputes` : ''}{x.valid_until ? ` · valid until ${x.valid_until}` : ''}</div>
            <div className="row" style={{ marginTop: 4 }}>{x.payee?.status === 'verified' ? <Proof>Verified payee</Proof> : <Chip>Payee {words(x.payee?.status)}</Chip>}{x.quote_evidence ? <EvidenceLink id={x.quote_evidence} label="The quote" variant="preview" /> : null}</div>
          </RadioCard>
        ))}
        {r.single_quote_exception_reason ? <p className="muted">Only one quote: {r.single_quote_exception_reason}</p> : null}
      </Section>
      {choosing && chosen ? (
        <ApproveMoney amount={chosen.amount} payee={chosen.payee?.name ?? chosen.contractor?.name} payeeLines={<div className="mono" style={{ fontSize: 14 }}>Account ending {chosen.payee?.account_last4}</div>}
          holdLabel="Hold to approve this quote"
          note={<p className="muted" style={{ margin: 0, fontSize: 14 }}>After you approve, you pay the amount into the bank, which holds it. The contractor is paid only after the work is inspected, and after two Tenmina staff approve.</p>}
          onApprove={async (code) => { await stepUp(code); await a.post(`/v1/repairs/${id}/quote-approvals`, { quote_id: chosen.id, confirm_amount: chosen.amount }); q.mutate(); a.show('Quote approved'); }} />
      ) : null}
      {r.owner_approved_at ? <Proof>You approved a quote <When value={r.owner_approved_at} /></Proof> : null}
      {r.escrow ? <Link className="btn btn-primary" href={`/property/escrows/${r.escrow}`}>Money at the bank · {r.escrow_reference}</Link> : null}
      <KV items={[['Inspection', r.inspection ? words(r.inspection.status ?? 'booked') : '—'], ['Work done', r.work_done_at ? <When key="w" value={r.work_done_at} /> : '—'], ['Paid', r.paid_at ? <When key="p" value={r.paid_at} /> : '—']]} />
      {r.release_instruction ? <Link className="btn btn-ghost" href={`/property/releases/${r.release_instruction}`}>The payment to the contractor</Link> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
