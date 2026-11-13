'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, useGet } from '@tenmina/web-ui';
import { PageHead, list, useAction, useCountry, words, type Any } from '@/components/kit';

/** SCR-PTL-53: plan an event. The budget is held by the bank and paid to verified vendors against proof. */
export default function NewEvent() {
  const country = useCountry();
  const router = useRouter();
  const fams = useGet<Any>('/v1/family-members');
  const [f, setF] = useState({ kind: 'funeral', name: '', event_date: '', locality: '', budget: '', confirmer: '' });
  const a = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/events', { country: country.code, kind: f.kind, name: f.name, event_date: f.event_date, locality: f.locality, budget: { amount: f.budget, currency: country.currency }, confirmer_family_member_id: f.confirmer || null }), undefined, (r) => router.push(`/family/events/${r.id}`)); }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Events" title="Plan an event" sub="Tenmina checks each vendor. The bank holds the budget and pays vendors only against their invoice and proof of delivery." />
      <Field label="Kind"><Select value={f.kind} onChange={set('kind')}>{['funeral', 'wedding', 'naming', 'anniversary', 'other'].map((k) => <option key={k} value={k}>{words(k)}</option>)}</Select></Field>
      <Field label="Name"><Input value={f.name} onChange={set('name')} required placeholder="For example: Funeral of Opanyin Kwame Mensah" /></Field>
      <Field label="Date"><Input type="date" value={f.event_date} onChange={set('event_date')} required /></Field>
      <Field label="Town"><Input value={f.locality} onChange={set('locality')} /></Field>
      <Field label={`Budget (${country.currency})`}><Input inputMode="decimal" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value.replace(/[^\d.]/g, '') })} required /></Field>
      <Field label="Who confirms deliveries at the event"><Select value={f.confirmer} onChange={set('confirmer')}><option value="">Choose later</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy}>Create the event</Button>
    </form>
  );
}
