'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Select } from '@tenmina/web-ui';
import { PageHead, useAction, useCountry, type Any } from '@/components/kit';

const RELATIONSHIPS = ['mother', 'father', 'grandmother', 'grandfather', 'sister', 'brother', 'son', 'daughter', 'aunt', 'uncle', 'niece', 'nephew', 'cousin', 'spouse', 'other'];

/** SCR-PTL-38: add a family member. Who may confirm care visits is set here. */
export default function NewMember() {
  const country = useCountry();
  const router = useRouter();
  const [f, setF] = useState({ full_name: '', relationship: 'mother', phone: '', address: '', may_confirm_visits: false });
  const a = useAction();
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/family-members', { ...f, country: country.code }), undefined, (m) => router.push(`/family/members/${m.id}`)); }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Family" title="Add a family member" />
      <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required /></Field>
      <Field label="Relationship to you"><Select value={f.relationship} onChange={(e) => setF({ ...f, relationship: e.target.value })}>{RELATIONSHIPS.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}</Select></Field>
      <Field label="Their phone number" hint="Used for visit confirmation codes. They never need an account."><Input type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
      <Field label="Address at home"><Input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></Field>
      <label className="row" style={{ flexWrap: 'nowrap', gap: 10 }}><input type="checkbox" checked={f.may_confirm_visits} onChange={(e) => setF({ ...f, may_confirm_visits: e.target.checked })} style={{ width: 24, height: 24, accentColor: '#0b0b0b' }} /><span>They may confirm care visits</span></label>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy}>Add</Button>
    </form>
  );
}
