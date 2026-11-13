'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Field, Input, KV, ProblemBox, Select, Skeleton, When, useGet } from '@tenmina/web-ui';
import { PageHead, Section, list, useAction, words, type Any } from '@/components/kit';

/** CMP-26 institution card: status, what was checked, the verified account (last four only), the contact role. */
export default function Institution() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/institutions/${id}`);
  const ben = useGet<Any>(`/v1/institutions/${id}/beneficiaries`, undefined, { shouldRetryOnError: false });
  const fams = useGet<Any>('/v1/family-members');
  const [fm, setFm] = useState('');
  const [ref, setRef] = useState('');
  const a = useAction();
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const i = q.data;
  const verified = i.status === 'verified';
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={words(i.type)} title={i.legal_name} sub={i.address} />
      <div className={verified ? 'card' : 'card-ink'} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        {verified ? <span className="proof">✓ Verified</span> : <Chip>{words(i.status)}</Chip>}
        <div>{i.status_text}{i.verified_at ? <> <When value={i.verified_at} />.</> : null}{i.not_eligible_reason ? <div className="muted">{i.not_eligible_reason}</div> : null}</div>
      </div>
      <Section title="What Tenmina checked">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          {(i.checklist ?? []).map((c: Any) => (
            <div key={c.key} className="check-row"><span className={`tick ${c.done ? 'done' : ''}`} aria-hidden>{c.done ? '✓' : ''}</span><div>{c.label}{c.detail ? <div className="muted" style={{ fontSize: 13 }}>{c.detail}</div> : null}</div><span /></div>
          ))}
        </div>
      </Section>
      {i.payee ? (
        <Section title="The account we pay">
          <KV items={[['Account name', i.payee.account_name], ['Account ending', <span key="l" className="mono">{i.payee.account_last4}</span>], ['Name check', i.payee.name_match === 'matched' ? <span key="m" className="proof">✓ Bank confirmed the name</span> : <span key="m" className="unmatched">Name not matched</span>]]} />
        </Section>
      ) : null}
      {(i.contacts ?? []).length ? <Section title="Who confirms bills">{i.contacts.map((c: Any) => <div key={c.id} className="card">{c.role_title || 'Named contact'}{c.may_confirm_invoices ? ' · confirms bills' : ''}</div>)}</Section> : null}
      <Section title="Family members it serves">
        {list(ben.data).map((b: Any) => <div key={b.id} className="card spread"><span>{b.family_member_name}</span><span className="mono muted">{b.institution_account_ref}</span></div>)}
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('b', () => a.post(`/v1/institutions/${id}/beneficiaries`, { family_member_id: fm, institution_account_ref: ref }), 'Added', () => { ben.mutate(); setFm(''); setRef(''); }); }}>
          <Field label="Family member"><Select value={fm} onChange={(e) => setFm(e.target.value)} required><option value="">Choose</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
          <Field label="Their number at this institution (optional)" hint="Student number, patient number or account number"><Input value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
          <Button variant="dark" type="submit" busy={a.busy === 'b'}>Add</Button>
        </form>
      </Section>
      <ProblemBox error={a.error} />
      {verified ? <Link className="btn btn-primary" href={`/family/invoices/new?institution=${id}`}>Add a bill from {i.legal_name}</Link> : null}
      {a.toast}
    </div>
  );
}
