'use client';
import { useState } from 'react';
import { Button, Chip, Field, Input, ProblemBox, Select, When, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, Section, useAction, words, type Any } from '@/components/kit';

/** W-02 · SCR-PTL-04: identity check through the provider. Needed before the first report or escrow. */
export default function Identity() {
  const { me, refresh } = useSession();
  const q = useGet<Any[]>('/v1/me/identity-checks');
  const a = useAction();
  const [f, setF] = useState({ document_type: 'passport', document_number: '' });
  const status = (me as Any)?.id_check_status;
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Confirm your identity" sub="We check your document with an identity provider. We do this once, before your first report or escrow." />
      {status === 'passed' ? <Proof>Your identity is confirmed</Proof> : null}
      {status !== 'passed' ? (
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post('/v1/me/identity-checks', f), 'Sent for checking', () => { q.mutate(); refresh(); }); }}>
          <Field label="Document"><Select value={f.document_type} onChange={(e) => setF({ ...f, document_type: e.target.value })}><option value="passport">Passport</option><option value="national_id">National ID card (for example a Ghana Card)</option><option value="residence_permit">Residence permit</option><option value="driving_licence">Driving licence</option></Select></Field>
          <Field label="Document number"><Input value={f.document_number} onChange={(e) => setF({ ...f, document_number: e.target.value })} required /></Field>
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={!!a.busy}>Check my identity</Button>
          <span className="muted" style={{ fontSize: 14 }}>If the provider cannot confirm it, a case manager checks your document by hand and tells you what to send.</span>
        </form>
      ) : null}
      <Section title="Checks">
        {(q.data ?? []).map((c: Any) => (
          <div key={c.id} className="card spread"><span>{words(c.document_type)} <span className="mono">{c.document_number}</span><div className="muted" style={{ fontSize: 13 }}><When value={c.created_at} /> · {words(c.method)}</div></span>{c.status === 'passed' ? <Proof>Passed</Proof> : <Chip>{words(c.status)}</Chip>}</div>
        ))}
      </Section>
      {a.toast}
    </Ink>
  );
}
