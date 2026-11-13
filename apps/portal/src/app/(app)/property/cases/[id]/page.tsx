'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Empty, ProblemBox, Skeleton, Steps, Textarea, Verdict, When, useGet, useSession } from '@tenmina/web-ui';
import { FilePick, PageHead, Section, list, postForm, useAction, words, type Any } from '@/components/kit';

/** W-07 · SCR-PTL-12: the case tracker, with document requests (SCR-PTL-13) and messages (SCR-PTL-19). */
export default function CaseTracker() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const c = useGet<Any>(`/v1/cases/${id}`);
  const reqs = useGet<Any>(`/v1/cases/${id}/document-requests`);
  const msgs = useGet<Any>(`/v1/cases/${id}/messages`);
  const reports = useGet<Any>('/v1/reports');
  const [body, setBody] = useState('');
  const a = useAction();
  if (c.isLoading) return <Skeleton lines={6} />;
  if (!c.data) return <ProblemBox error={c.error} />;
  const k = c.data;
  const open = list(reqs.data).filter((r: Any) => r.status === 'open' || r.status === 'requested' || r.status === 'pending');
  const done = list(reqs.data).filter((r: Any) => !open.includes(r));
  const myReports = list(reports.data).filter((r: Any) => r.case === id && r.status === 'released');
  const msgsSorted = [...list(msgs.data)].sort((x: Any, y: Any) => String(x.created_at).localeCompare(String(y.created_at)));
  const timeline = [...(k.status_messages ?? [])].sort((x: Any, y: Any) => String(x.created_at).localeCompare(String(y.created_at)));
  const latest = k.latest_status;
  const finished = ['released', 'closed', 'cancelled', 'completed'].includes(k.status);
  return (
    <div className="stack" style={{ gap: 20 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${words(k.product_line)} check · ${k.reference}`} title={k.title} />
      <div className="card-ink stack" style={{ gap: 6 }}>
        <span className="label" style={{ color: '#a9a69e' }}>{k.status === 'on_hold' ? 'Paused' : finished ? words(k.status) : 'Now'}</span>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{latest?.text || words(k.status)}</div>
        {k.status === 'on_hold' && k.hold_reason ? <div style={{ color: '#a9a69e' }}>{k.hold_reason}</div> : null}
        {latest?.next_expected_date ? <div className="mono" style={{ color: '#a9a69e', fontSize: 13 }}>Next update by <When value={latest.next_expected_date} /></div> : null}
      </div>
      {myReports.map((r: Any) => (
        <Link key={r.id} href={`/property/reports/${r.id}`} className="card card-link spread">
          <div><div className="label">Your report · version {r.version}</div><strong>Open the report</strong></div>
          <Verdict value={r.overall_verdict} />
        </Link>
      ))}
      {open.length ? (
        <Section title="We need something from you">
          {open.map((r: Any) => (
            <div key={r.id} className="needs-you" style={{ flexDirection: 'column', alignItems: 'stretch' }} id="requests">
              <div>
                <div className="label" style={{ color: '#0b0b0b' }}>Needs you{r.due_on ? <> · by <When value={r.due_on} /></> : null}</div>
                <div style={{ fontWeight: 800 }}>{r.title}</div>
                {r.description ? <div style={{ fontSize: 14 }}>{r.description}</div> : null}
              </div>
              <div className="row" style={{ background: '#fff', borderRadius: 12, padding: 6 }}>
                <FilePick label="Upload the file" busy={a.busy === r.id} onFile={(f) => { const fd = new FormData(); fd.append('file', f); a.run(r.id, () => postForm(`/v1/document-requests/${r.id}/responses`, fd), 'Thank you. We have the file.', () => { reqs.mutate(); c.mutate(); }); }} />
              </div>
            </div>
          ))}
          <p className="muted" style={{ fontSize: 14 }}>If we ask about the seller&apos;s identity, send the ID number, not a photo of the card. We check the number ourselves.</p>
        </Section>
      ) : null}
      <Section title="Timeline">
        {timeline.length ? <Steps items={[
          ...timeline.map((m: Any, i: number) => ({ label: m.text, state: (i === timeline.length - 1 && !finished ? 'now' : 'done') as 'done' | 'now', detail: new Date(m.message_date || m.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) })),
          ...(!finished && latest?.next_expected_date ? [{ label: 'Next step', state: 'next' as const, detail: `Expected by ${new Date(latest.next_expected_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}` }] : []),
        ]} /> : <Empty>The timeline starts when your case manager accepts the case.</Empty>}
      </Section>
      {done.length ? (
        <Section title="Documents you sent">
          {done.map((r: Any) => <div key={r.id} className="card spread"><span>{r.title}</span><Chip tone="lime">✓ Received <When value={r.received_at} /></Chip></div>)}
        </Section>
      ) : null}
      <Section title="Messages">
        <div className="stack" style={{ gap: 8 }}>
          {msgsSorted.length ? msgsSorted.map((m: Any) => (
            <div key={m.id} className={`msg ${m.sender?.id === me?.id ? 'mine' : ''}`}>
              <div className="label" style={{ color: 'inherit', opacity: 0.7 }}>{m.sender?.id === me?.id ? 'You' : m.sender?.name || 'Tenmina'} · <When value={m.created_at} withTime /></div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{m.body}</div>
            </div>
          )) : <p className="muted">No messages yet. Ask your case manager anything.</p>}
        </div>
        <form className="stack" onSubmit={(e) => { e.preventDefault(); a.run('msg', () => a.post(`/v1/cases/${id}/messages`, { body }), 'Sent', () => { setBody(''); msgs.mutate(); }); }}>
          <label className="field"><span>Message Tenmina</span><Textarea value={body} onChange={(e) => setBody(e.target.value)} required /></label>
          <Button variant="dark" type="submit" busy={a.busy === 'msg'} disabled={!body.trim()}>Send</Button>
        </form>
      </Section>
      <ProblemBox error={a.error} />
      <div className="row">
        {k.order ? <Link className="btn btn-ghost" href={`/property/orders/${k.order}`}>Order and receipt</Link> : null}
        {k.asset ? <Link className="btn btn-ghost" href={`/property/assets/${k.asset}`}>The property</Link> : null}
        <Link className="btn btn-ghost" href="/account/representatives">Share with a representative</Link>
      </div>
      {a.toast}
    </div>
  );
}
