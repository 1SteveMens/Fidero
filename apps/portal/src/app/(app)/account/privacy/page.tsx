'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Button, Chip, Field, ProblemBox, Select, Skeleton, Textarea, When, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, Section, list, useAction, words, type Any } from '@/components/kit';

/** SCR-PTL-34 and FR-DPR-001, FR-DPR-003: the privacy notice, a copy of my data, corrections. */
export default function Privacy() {
  const { refresh } = useSession();
  const notice = useGet<Any>('/v1/privacy-notices/current');
  const acc = useGet<Any[]>('/v1/me/privacy-acceptances');
  const reqs = useGet<Any[]>('/v1/me/data-requests');
  const a = useAction();
  const [f, setF] = useState({ type: 'access', details: '' });
  const accepted = (acc.data ?? []).some((x: Any) => x.version === notice.data?.version);
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Privacy and my data" />
      <Section title={notice.data?.title ?? 'Privacy notice'}>
        {notice.isLoading ? <Skeleton /> : notice.data ? (
          <div className="card stack">
            <span className="mono muted" style={{ fontSize: 12 }}>Version {notice.data.version} · published <When value={notice.data.published_at} /></span>
            <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{notice.data.text}</p>
            {accepted ? <Proof>You accepted this version</Proof> : <Button variant="action" busy={a.busy === 'acc'} onClick={() => a.run('acc', () => a.post('/v1/me/privacy-acceptances', { version: notice.data.version }), 'Accepted', () => { acc.mutate(); refresh(); })}>I have read it</Button>}
          </div>
        ) : <ProblemBox error={notice.error} />}
        {(acc.data ?? []).map((x: Any) => <div key={x.id} className="mono muted" style={{ fontSize: 12 }}>Accepted version {x.version} on <When value={x.accepted_at} withTime /> ({words(x.source)})</div>)}
      </Section>
      <Section title="Ask about your data">
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('req', () => a.post('/v1/me/data-requests', f), 'Request sent. We answer within the legal time limit.', () => { reqs.mutate(); setF({ type: 'access', details: '' }); }); }}>
          <Field label="What you want"><Select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="access">A copy of the data Tenmina holds about me</option><option value="correction">Correct something that is wrong</option><option value="erasure">Erase specific data</option></Select></Field>
          <Field label="Details"><Textarea value={f.details} onChange={(e) => setF({ ...f, details: e.target.value })} /></Field>
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={a.busy === 'req'}>Send the request</Button>
        </form>
        {(reqs.data ?? []).map((r: Any) => (
          <Link key={r.id} href={`/account/data-requests/${r.id}`} className="card card-link spread"><span>{words(r.type)}<div className="muted" style={{ fontSize: 14 }}>{r.details || '—'} · due <When value={r.due_on} /></div></span>{r.status === 'completed' ? <Proof>Done</Proof> : <Chip>{words(r.status)}</Chip>}</Link>
        ))}
      </Section>
      <div className="row"><Link className="btn btn-ghost" href="/property/sharing">Sharing and consent</Link><Link className="btn btn-ghost" href="/account/delete">Delete my account</Link></div>
      {a.toast}
    </Ink>
  );
}
