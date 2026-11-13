'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, Field, ProblemBox, Select, Textarea, useGet } from '@tenmina/web-ui';
import { PageHead, list, useAction, words, type Any } from '@/components/kit';

const CATS = ['title_or_documents', 'work_quality', 'payment', 'misrepresentation', 'delay', 'other'];

/** W-23: open a dispute on an escrow or a project. Releases freeze while it runs (RUL-15). */
function NewDispute() {
  const sp = useSearchParams();
  const router = useRouter();
  const esc = useGet<Any>('/v1/escrows');
  const proj = useGet<Any>('/v1/projects');
  const preset = sp.get('escrow') ? `escrow:${sp.get('escrow')}` : sp.get('project') ? `project:${sp.get('project')}` : '';
  const [subject, setSubject] = useState(preset);
  const [category, setCategory] = useState('other');
  const [reason, setReason] = useState('');
  const [statement, setStatement] = useState('');
  const a = useAction();
  const [st, sid] = subject.split(':');
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/disputes', { subject_type: st, subject_id: sid, category, reason, statement }), undefined, (d) => router.push(`/property/disputes/${d.id}`)); }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label="Dispute" title="Open a dispute" sub="While a dispute is open, no money can move on that escrow or project. Both sides get a deadline to answer and send evidence." />
      <Field label="About">
        <Select value={subject} onChange={(e) => setSubject(e.target.value)} required>
          <option value="">Choose</option>
          {list(esc.data).filter((x: Any) => !['released', 'cancelled', 'closed'].includes(x.status)).map((x: Any) => <option key={x.id} value={`escrow:${x.id}`}>Escrow {x.reference}: {x.title}</option>)}
          {list(proj.data).map((p: Any) => <option key={p.id} value={`project:${p.id}`}>Project: {p.name || p.title}</option>)}
        </Select>
      </Field>
      <Field label="What kind of problem"><Select value={category} onChange={(e) => setCategory(e.target.value)}>{CATS.map((c) => <option key={c} value={c}>{words(c)}</option>)}</Select></Field>
      <Field label="In one sentence"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></Field>
      <Field label="Your statement (optional)" hint="You can add photos and documents on the next page."><Textarea value={statement} onChange={(e) => setStatement(e.target.value)} /></Field>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy} disabled={!subject || !reason.trim()}>Open the dispute</Button>
    </form>
  );
}

export default function Page() {
  return <Suspense><NewDispute /></Suspense>;
}
