'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, useSession } from '@tenmina/web-ui';
import { PageHead, Upload, useAction, useCountry, type Any } from '@/components/kit';

/** SCR-PTL-46: register a property for management. Ownership documents first; a condition inspection follows. */
export default function NewProperty() {
  const { me } = useSession();
  const country = useCountry();
  const router = useRouter();
  const [f, setF] = useState({ title: '', locality: '', address: '', region: '', ghana_post_gps: '' });
  const [docs, setDocs] = useState<Any[]>([]);
  const a = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/managed-properties', { ...f, country: country.code, ownership_evidence_ids: docs.map((d) => d.id) }), undefined, (p) => router.push(`/projects/properties/${p.id}`)); }}>
      <PageHead back={{ href: '/projects', label: 'Projects' }} label="Property management" title="Register a property" sub="Tenmina checks you own it and inspects its condition with photos. Rent is paid by the tenant into your own bank account, never to Tenmina." />
      <Field label="Name"><Input value={f.title} onChange={set('title')} required placeholder="For example: Family house in Kumasi" /></Field>
      <Field label="Town or area"><Input value={f.locality} onChange={set('locality')} required /></Field>
      <Field label="Address"><Input value={f.address} onChange={set('address')} /></Field>
      <Field label="Region"><Input value={f.region} onChange={set('region')} /></Field>
      <Field label="Ghana Post GPS address"><Input value={f.ghana_post_gps} onChange={set('ghana_post_gps')} /></Field>
      <div className="card stack">
        <strong>Proof that you own it</strong>
        <span className="muted" style={{ fontSize: 14 }}>An indenture, land title or site plan in your name.</span>
        {me ? <Upload subject={{ type: 'pmg_owner_document', id: me.id, role: 'ownership', country: country.code }} label="Add a document" onDone={(ev) => setDocs([...docs, ev])} /> : null}
        {docs.map((d) => <small key={d.id} className="muted">✓ {d.original_name || 'Document'} stored</small>)}
      </div>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy} disabled={!docs.length}>Register the property</Button>
    </form>
  );
}
