'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Empty, Field, Input, ProblemBox, Select, Skeleton, Tabs, useGet } from '@tenmina/web-ui';
import { Item, PageHead, list, useAction, useCountry, words, type Any } from '@/components/kit';

const TYPES = ['school', 'university', 'hospital', 'clinic', 'pharmacy', 'utility', 'government_agency'];

/** W-26 · SCR-PTL-39: use a verified institution or propose a new one. Nothing is paid until it is verified (RUL-22). */
export default function NewInstitution() {
  const country = useCountry();
  const router = useRouter();
  const [tab, setTab] = useState('search');
  const [search, setSearch] = useState('');
  const q = useGet<Any>('/v1/institutions', { country: country.code, search: search || undefined });
  const [f, setF] = useState({ type: 'school', legal_name: '', address: '', phone: '', email: '', proposed_bank_name: '', proposed_account_number: '', proposed_account_name: '' });
  const a = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Schools, hospitals and providers" title="Add an institution" />
      <Tabs current={tab} onChange={setTab} items={[{ key: 'search', label: 'Find one' }, { key: 'propose', label: 'Propose a new one' }]} />
      {tab === 'search' ? (
        <div className="stack">
          <Field label="Name"><Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="For example: Accra Hills School" /></Field>
          {q.isLoading ? <Skeleton /> : list(q.data).length ? list(q.data).map((i: Any) => (
            <Item key={i.id} href={`/family/institutions/${i.id}`} meta={`${words(i.type)} · ${i.address || ''}`} title={i.legal_name} sentence={i.status_text} chip={i.status === 'verified' ? <span className="proof">✓ Verified</span> : undefined} />
          )) : <Empty>Not found. Propose it and Tenmina will check it.</Empty>}
        </div>
      ) : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/institutions', { ...f, country: country.code }), undefined, (i) => router.push(`/family/institutions/${i.id}`)); }}>
          <p className="muted" style={{ margin: 0 }}>Tenmina checks its registration, a bank account in its own name and a named contact who confirms bills. Nothing is paid until then. We never pay in cash.</p>
          <Field label="Type"><Select value={f.type} onChange={set('type')}>{TYPES.map((t) => <option key={t} value={t}>{words(t)}</option>)}</Select></Field>
          <Field label="Name"><Input value={f.legal_name} onChange={set('legal_name')} required /></Field>
          <Field label="Town and address"><Input value={f.address} onChange={set('address')} /></Field>
          <Field label="Phone (the office, not a person)"><Input type="tel" value={f.phone} onChange={set('phone')} /></Field>
          <Field label="Email"><Input type="email" value={f.email} onChange={set('email')} /></Field>
          <h3 style={{ margin: '8px 0 0' }}>Their bank account, if you know it</h3>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Tenmina confirms it with the bank in the institution&apos;s own name before any payment.</p>
          <Field label="Bank"><Input value={f.proposed_bank_name} onChange={set('proposed_bank_name')} /></Field>
          <Field label="Account number"><Input inputMode="numeric" value={f.proposed_account_number} onChange={set('proposed_account_number')} /></Field>
          <Field label="Account name"><Input value={f.proposed_account_name} onChange={set('proposed_account_name')} /></Field>
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={!!a.busy}>Ask Tenmina to check it</Button>
        </form>
      )}
    </div>
  );
}
