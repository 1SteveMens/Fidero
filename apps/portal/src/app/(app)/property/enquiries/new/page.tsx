'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Textarea } from '@tenmina/web-ui';
import { PageHead, useAction, useCountry, type Any } from '@/components/kit';

/** Ask Tenmina to find a checked plot (FR-LST-010). */
export default function NewEnquiry() {
  const country = useCountry();
  const router = useRouter();
  const [f, setF] = useState({ message: '', wanted_region: '', wanted_locality: '', budget: '' });
  const a = useAction();
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/enquiries', { country: country.code, message: f.message, wanted_region: f.wanted_region, wanted_locality: f.wanted_locality, budget: f.budget ? { amount: f.budget, currency: country.currency } : undefined }), undefined, (r) => router.push(`/property/enquiries/${r.id}`)); }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label="Find a plot" title="Tell us what you want" />
      <Field label="What are you looking for?"><Textarea value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} required placeholder="For example: a plot for a family house, about 100 x 70 ft." /></Field>
      <Field label="Region"><Input value={f.wanted_region} onChange={(e) => setF({ ...f, wanted_region: e.target.value })} /></Field>
      <Field label="Town or area"><Input value={f.wanted_locality} onChange={(e) => setF({ ...f, wanted_locality: e.target.value })} /></Field>
      <Field label={`Budget (${country.currency}, optional)`}><Input inputMode="numeric" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value.replace(/\D/g, '') })} /></Field>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy}>Send</Button>
    </form>
  );
}
