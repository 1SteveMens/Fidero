'use client';
import { useState } from 'react';
import { Button, Chip, Field, Input, ProblemBox, Select, Skeleton, When, useGet } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, Section, list, useAction, words, type Any } from '@/components/kit';

/** FR-ACC-008: a representative follows a case read-only. They never approve a payment for you. */
export default function Representatives() {
  const q = useGet<Any>('/v1/me/representatives');
  const cases = useGet<Any>('/v1/cases');
  const mine = useGet<Any>('/v1/me/represented');
  const a = useAction();
  const [f, setF] = useState({ email: '', full_name: '', subject: '' });
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Representatives" sub="Someone you trust, for example a relative at home, can follow a case and see its messages. They cannot approve any payment." />
      {q.isLoading ? <Skeleton /> : list(q.data).map((g: Any) => (
        <div key={g.id} className="card stack" style={{ gap: 6 }}>
          <div className="spread"><strong>{g.full_name || g.email}</strong>{g.status === 'active' ? <Proof>Active</Proof> : <Chip>{words(g.status)}</Chip>}</div>
          <span className="muted" style={{ fontSize: 14 }}>{g.email} · {words(g.subject_type)} · read only{g.expires_at ? <> · until <When value={g.expires_at} /></> : null}</span>
          {g.status !== 'revoked' ? <Button variant="ghost" size="sm" busy={a.busy === g.id} onClick={() => a.run(g.id, () => a.post(`/v1/me/representatives/${g.id}`, undefined, 'DELETE'), 'Removed', () => q.mutate())}>Remove</Button> : null}
        </div>
      ))}
      <Section title="Invite someone">
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); const [subject_type, subject_id] = f.subject.split(':'); a.run('add', () => a.post('/v1/me/representatives', { email: f.email, full_name: f.full_name, subject_type, subject_id }), 'Invitation sent', () => { q.mutate(); setF({ email: '', full_name: '', subject: '' }); }); }}>
          <Field label="Their name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Their email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required /></Field>
          <Field label="Which case"><Select value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} required><option value="">Choose</option>{list(cases.data).map((c: Any) => <option key={c.id} value={`case:${c.id}`}>{c.reference}: {c.title}</option>)}</Select></Field>
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={a.busy === 'add'}>Send the invitation</Button>
        </form>
      </Section>
      {list(mine.data).length ? <Section title="People you represent">{list(mine.data).map((g: Any) => <div key={g.id} className="card">{g.client?.full_name} · {words(g.subject_type)}</div>)}</Section> : null}
      {a.toast}
    </Ink>
  );
}
