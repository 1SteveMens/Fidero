'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Button, Field, ProblemBox, Skeleton, Steps, Textarea, When, useGet, useSession } from '@tenmina/web-ui';
import { ActionDialog, PageHead, Section, Upload, useAction, words, type Any } from '@/components/kit';

const ORDER = ['open', 'awaiting_response', 'evidence', 'decision', 'closed'];

/** W-23 · SCR-PTL-29: a dispute. Releases stay frozen until it is resolved (RUL-15). */
export default function Dispute() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const q = useGet<Any>(`/v1/disputes/${id}`);
  const a = useAction();
  const [text, setText] = useState('');
  const [ev, setEv] = useState<Any[]>([]);
  const [w, setW] = useState(false);
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const d = q.data;
  const open = !['closed', 'withdrawn'].includes(d.status);
  const mySide = (d.parties ?? []).find((p: Any) => p.name === me?.full_name);
  const idx = d.status === 'referred' ? 3 : ORDER.indexOf(d.status);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${d.reference} · ${words(d.category)}`} title={d.subject_label} />
      {open && d.escrow_id ? <Blocked title="Payments frozen">No money can move on this escrow until the dispute is resolved.</Blocked> : null}
      <p style={{ margin: 0 }}>{d.reason}</p>
      <Steps items={[
        { label: 'The other side answers', state: idx >= 2 ? 'done' : 'now', detail: `By ${d.response_due}` },
        { label: 'Both sides send evidence', state: d.status === 'evidence' ? 'now' : idx > 2 ? 'done' : 'next', detail: `By ${d.evidence_due}` },
        { label: d.status === 'referred' ? `With the mediator ${d.mediator}` : 'Tenmina decides', state: ['decision', 'referred'].includes(d.status) ? 'now' : idx > 3 ? 'done' : 'next', detail: `By ${d.decision_due}` },
      ]} />
      {d.decision ? <Section title="Decision"><div className="card"><strong>{words(d.decision_outcome)}</strong>{d.in_favour_of ? <> · in favour of {words(d.in_favour_of)}</> : null}<p style={{ margin: '6px 0 0' }}>{d.decision}</p>{d.decided_at ? <div className="mono muted" style={{ fontSize: 12 }}><When value={d.decided_at} withTime /></div> : null}</div></Section> : null}
      <Section title="Statements">
        {(d.statements ?? []).map((s: Any) => (
          <div key={s.id} className={`msg ${s.party_name === me?.full_name ? 'mine' : ''}`}>
            <div className="label" style={{ color: 'inherit', opacity: 0.7 }}>{s.party_name} · {words(s.kind)} · <When value={s.created_at} /></div>
            {s.text}{s.evidence_ids?.length ? <div style={{ fontSize: 13, opacity: 0.8 }}>{s.evidence_ids.length} file(s) attached</div> : null}
          </div>
        ))}
      </Section>
      {open ? (
        <section className="card stack">
          <h3 style={{ margin: 0 }}>Add a statement or evidence</h3>
          <Field label="What happened"><Textarea value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <Upload subject={{ type: 'dispute', id }} label="Attach a photo or document" onDone={(e) => setEv([...ev, e])} />
          {ev.length ? <small className="muted">{ev.length} file(s) ready to send</small> : null}
          <Button variant="dark" disabled={!text.trim()} busy={a.busy === 's'} onClick={() => a.run('s', () => a.post(`/v1/disputes/${id}/statements`, { text, evidence_ids: ev.map((x) => x.id) }), 'Sent', () => { setText(''); setEv([]); q.mutate(); })}>Send</Button>
          {mySide && !mySide.evidence_complete_at && d.status === 'evidence' ? <Button variant="ghost" busy={a.busy === 'c'} onClick={() => a.run('c', () => a.post(`/v1/disputes/${id}/evidence-complete`, {}), 'Marked complete', () => q.mutate())}>I have sent all my evidence</Button> : null}
        </section>
      ) : null}
      <ProblemBox error={a.error} />
      <div className="row">
        {d.escrow_id ? <Link className="btn btn-ghost" href={`/property/escrows/${d.escrow_id}`}>The escrow</Link> : null}
        {d.project_id ? <Link className="btn btn-ghost" href={`/projects/${d.project_id}`}>The project</Link> : null}
        {open && d.parties?.[0]?.name === me?.full_name ? <Button variant="ghost" onClick={() => setW(true)}>Withdraw the dispute</Button> : null}
      </div>
      <ActionDialog open={w} onClose={() => setW(false)} title="Withdraw the dispute" submit="Withdraw" busy={a.busy === 'w'} error={a.error}
        onSubmit={() => a.run('w', () => a.post(`/v1/disputes/${id}/withdrawals`, { reason }), 'Withdrawn', () => { setW(false); q.mutate(); })}>
        <Field label="Why (optional)"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
