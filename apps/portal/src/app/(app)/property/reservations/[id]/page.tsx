'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Field, NeedsYou, ProblemBox, Skeleton, Steps, Textarea, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, PageHead, useAction, words, type Any } from '@/components/kit';

/** SCR-PTL-28: a reservation. A fresh search runs and an escrow is proposed (FR-LST-005, FR-CASE-014). */
export default function Reservation() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/reservations/${id}`);
  const a = useAction();
  const [w, setW] = useState(false);
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={5} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const r = q.data;
  const active = r.status === 'active';
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${r.reference} · ${words(r.status)}`} title={r.listing?.title} />
      {active ? <p style={{ margin: 0 }}>Held for you until <When value={r.expires_at} withTime />.</p> : r.end_reason ? <p>{r.end_reason}</p> : null}
      {active && r.escrow?.status === 'proposed' ? <NeedsYou title="Accept the escrow terms" detail="The bank opens the escrow once everyone accepts." href={`/property/escrows/${r.escrow.id}`} /> : null}
      <Steps items={[
        { label: 'Reserved', state: 'done', detail: new Date(r.created_at).toLocaleDateString('en-GB') },
        { label: 'Fresh search at the registry', state: r.fresh_search_status === 'passed' || r.fresh_search_status === 'clear' ? 'done' : 'now', detail: r.fresh_search_date ? `Result ${r.fresh_search_date}` : words(r.fresh_search_status) },
        { label: 'Escrow agreed and funded', state: r.escrow && ['funded', 'ready_to_release', 'released', 'partly_released'].includes(r.escrow.status) ? 'done' : 'next', detail: r.escrow ? `${r.escrow.reference} · ${words(r.escrow.status)}` : undefined },
      ]} />
      {r.fresh_search_note ? <div className="card">{r.fresh_search_note}</div> : null}
      <div className="row">
        {r.escrow ? <Link className="btn btn-dark" href={`/property/escrows/${r.escrow.id}`}>Open the escrow</Link> : null}
        {r.fresh_search_case_id ? <Link className="btn btn-ghost" href={`/property/cases/${r.fresh_search_case_id}`}>The fresh search</Link> : null}
        {r.listing ? <Link className="btn btn-ghost" href={`/property/listings/${r.listing.id}`}>The listing</Link> : null}
      </div>
      {active ? <button className="btn btn-ghost" onClick={() => setW(true)}>Withdraw the reservation</button> : null}
      <ActionDialog open={w} onClose={() => setW(false)} title="Withdraw the reservation" submit="Withdraw" busy={!!a.busy} error={a.error}
        onSubmit={() => a.run('w', () => a.post(`/v1/reservations/${id}/withdrawals`, { reason }), 'Withdrawn', () => { setW(false); q.mutate(); })}>
        <Field label="Why (optional)"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
