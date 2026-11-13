'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Field, KV, ProblemBox, Skeleton, Textarea, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, EvidenceLink, PageHead, Proof, Section, useAction, words, type Any } from '@/components/kit';

/** SCR-PTL-44: one care visit. Check-in and out, tasks with photos, the family's confirmation, then payment. */
export default function Visit() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/care-visits/${id}`);
  const a = useAction();
  const [cancel, setCancel] = useState(false);
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const v = q.data;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: `/family/care/${v.plan}`, label: v.plan_reference }} label={words(v.status)} title={`${v.carer?.name ?? 'Carer'} visits ${v.family_member?.full_name ?? ''}`} />
      <KV items={[
        ['Window', <span key="w"><When value={v.window_start} withTime /> to {new Date(v.window_end).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>],
        ['Checked in', v.check_in ? <span key="i"><When value={v.check_in.at} withTime />{v.check_in.within_radius ? ' · at the address' : ` · ${v.check_in.distance_m} m away`}</span> : '—'],
        ['Checked out', v.check_out ? <When key="o" value={v.check_out.at} withTime /> : '—'],
        ['Late', v.late_minutes ? `${v.late_minutes} minutes` : '—'],
        ['Payment', v.payment],
      ]} />
      {v.confirmed_at ? <Proof>Confirmed by the family <When value={v.confirmed_at} withTime /></Proof> : v.status === 'missed' ? <Chip>The carer did not come</Chip> : <Chip>Not confirmed yet</Chip>}
      {v.needs_review_reason ? <div className="card">{v.needs_review_reason}</div> : null}
      <Section title={`Tasks (${v.items_done ?? 0} of ${v.items?.length ?? 0} done)`}>
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          {(v.items ?? []).map((it: Any) => (
            <div key={it.key} className="check-row">
              <span className={`tick ${it.outcome === 'done' ? 'done' : ''}`}>{it.outcome === 'done' ? '✓' : it.outcome === 'not_done' ? '✕' : ''}</span>
              <div>{it.label}{it.reason ? <div className="muted" style={{ fontSize: 13 }}>{it.reason}</div> : null}{it.reading ? <div className="mono" style={{ fontSize: 13, overflowWrap: "anywhere" }}>{typeof it.reading === "object" ? Object.entries(it.reading).map(([k, x]) => `${k}: ${x}`).join(", ") : String(it.reading)}</div> : null}</div>
              {it.evidence ? <EvidenceLink id={it.evidence} label="Photo" variant="preview" /> : <span />}
            </div>
          ))}
        </div>
      </Section>
      {v.instruction_id ? <Link href={`/property/releases/${v.instruction_id}`} className="btn btn-dark">The payment to the carer</Link> : null}
      <ProblemBox error={a.error} />
      {['scheduled'].includes(v.status) ? <Button variant="ghost" onClick={() => setCancel(true)}>Cancel this visit</Button> : null}
      <ActionDialog open={cancel} onClose={() => setCancel(false)} title="Cancel the visit" submit="Cancel the visit" busy={!!a.busy} error={a.error}
        onSubmit={() => a.run('c', () => a.post(`/v1/care-visits/${id}/cancel`, { reason }), 'Cancelled', () => { setCancel(false); q.mutate(); })}>
        <Field label="Why"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></Field>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
