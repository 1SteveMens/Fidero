'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, Textarea, useGet } from '@tenmina/web-ui';
import { FilePick, PageHead, fileFields, list, useAction, useCountry, type Any } from '@/components/kit';

/** SCR-PTL-40, first half: upload a bill from a verified institution. Tenmina checks it with the institution. */
function NewInvoice() {
  const sp = useSearchParams();
  const router = useRouter();
  const country = useCountry();
  const inst = useGet<Any>('/v1/institutions', { country: country.code });
  const fams = useGet<Any>('/v1/family-members');
  const [f, setF] = useState({ institution_id: sp.get('institution') || '', family_member_id: sp.get('member') || '', institution_reference: '', amount: '', due_on: '', description: '' });
  const [file, setFile] = useState<File | null>(null);
  const a = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  async function submit() {
    await a.run('go', async () => {
      const doc = file ? await fileFields(file) : {};
      return a.post<Any>('/v1/invoices', { ...doc, institution_id: f.institution_id, family_member_id: f.family_member_id || null, institution_reference: f.institution_reference, amount: { amount: f.amount, currency: country.currency }, due_on: f.due_on || null, description: f.description });
    }, undefined, (inv) => router.push(`/family/invoices/${inv.id}`));
  }
  const institutions = list(inst.data).filter((i: Any) => i.status !== 'not_eligible');
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Pay a bill" title="Add a bill" sub="Tenmina checks every bill with the institution before you approve it. Money goes only to the institution's verified account." />
      <Field label="Institution"><Select value={f.institution_id} onChange={set('institution_id')} required><option value="">Choose</option>{institutions.map((i: Any) => <option key={i.id} value={i.id}>{i.legal_name}{i.status === 'verified' ? '' : ' (being checked)'}</option>)}</Select></Field>
      <Field label="For"><Select value={f.family_member_id} onChange={set('family_member_id')}><option value="">Choose</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
      <Field label="Bill number on the invoice"><Input value={f.institution_reference} onChange={set('institution_reference')} required /></Field>
      <Field label={`Amount (${country.currency})`}><Input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.replace(/[^\d.]/g, '') })} required /></Field>
      <Field label="Due date"><Input type="date" value={f.due_on} onChange={set('due_on')} /></Field>
      <Field label="What it is for"><Textarea value={f.description} onChange={set('description')} placeholder="For example: Term 2 fees" /></Field>
      <div className="card stack">
        <strong>The bill itself</strong>
        <span className="muted" style={{ fontSize: 14 }}>A photo or PDF. It is stored with its fingerprint.</span>
        <FilePick label={file ? `Chosen: ${file.name}` : 'Choose the file'} onFile={setFile} />
      </div>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy}>Send for checking</Button>
    </form>
  );
}

export default function Page() { return <Suspense><NewInvoice /></Suspense>; }
