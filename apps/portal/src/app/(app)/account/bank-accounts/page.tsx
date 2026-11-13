'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Button, Chip, Field, Input, ProblemBox, Select, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, Section, Upload, list, useAction, useCountry, words, type Any } from '@/components/kit';

/** The client's own bank accounts (rent destination, refunds). Tenmina verifies each with a bank letter. */
export default function BankAccounts() {
  const { me } = useSession();
  const country = useCountry();
  const q = useGet<Any>('/v1/bank-accounts');
  const a = useAction();
  const [f, setF] = useState({ bank_name: '', branch: '', account_number: '', account_name: '', purpose: 'rent_destination' });
  const [letter, setLetter] = useState<Any>(null);
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Bank accounts" sub="Your own accounts at home, for rent from a tenant. Tenmina checks each one with a letter from your bank." />
      {q.isLoading ? <Skeleton /> : list(q.data).map((b: Any) => (
        <Link key={b.id} href={`/account/bank-accounts/${b.id}`} className="card card-link spread" style={{ flexWrap: 'nowrap' }}>
          <span><strong>{b.bank_name}</strong> · ending {b.account_number_last4}<div className="muted" style={{ fontSize: 14 }}>{b.account_name} · {words(b.purpose)}</div></span>
          {b.verification_status === 'verified' ? <Proof>Verified</Proof> : <Chip tone={['unverified', 'rejected'].includes(b.verification_status) ? 'orange' : undefined}>{words(b.verification_status)}</Chip>}
        </Link>
      ))}
      <Section title="Add an account">
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('add', () => a.post('/v1/bank-accounts', { ...f, country: country.code, evidence: letter?.id ?? null }), 'Added. Tenmina will check it.', () => { q.mutate(); setLetter(null); setF({ bank_name: '', branch: '', account_number: '', account_name: '', purpose: 'rent_destination' }); }); }}>
          <Field label="Bank"><Input value={f.bank_name} onChange={(e) => setF({ ...f, bank_name: e.target.value })} required /></Field>
          <Field label="Branch"><Input value={f.branch} onChange={(e) => setF({ ...f, branch: e.target.value })} /></Field>
          <Field label="Account number"><Input inputMode="numeric" value={f.account_number} onChange={(e) => setF({ ...f, account_number: e.target.value })} required /></Field>
          <Field label="Name on the account"><Input value={f.account_name} onChange={(e) => setF({ ...f, account_name: e.target.value })} required /></Field>
          <Field label="Used for"><Select value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })}><option value="rent_destination">Rent from my tenant</option><option value="refund">Refunds</option></Select></Field>
          {me ? <Upload subject={{ type: 'pmg_owner_document', id: me.id, role: 'bank_letter', country: country.code }} label={letter ? 'Bank letter attached' : 'Attach a letter from the bank'} onDone={setLetter} /> : null}
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={a.busy === 'add'}>Add the account</Button>
        </form>
      </Section>
      {a.toast}
    </Ink>
  );
}
