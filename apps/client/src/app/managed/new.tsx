import { useState } from 'react';
import { router } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Label, Panel, Screen, T } from '@tenmina/ui';
import { Field, ProblemBox, useAction, useSession } from '@tenmina/mobile';
import { AddFile, FileRow, type StoredEvidence } from '../../components/files';
import { useCountry } from '../../components/country';

/**
 * Register a property for management in the app (SCR-PTL-46, FR-PMG-001):
 * proof of ownership first, from Files or the photo library; a condition
 * inspection with photos follows. Rent goes from the tenant into the owner's
 * own bank account, never to Tenmina.
 */
export default function NewManagedProperty() {
  const { me } = useSession();
  const country = useCountry();
  const act = useAction();
  const [f, setF] = useState({ title: '', locality: '', address: '', region: '', ghana_post_gps: '' });
  const [docs, setDocs] = useState<StoredEvidence[]>([]);
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const ready = !!f.title.trim() && !!f.locality.trim() && docs.length > 0 && !!country.code;

  async function register() {
    const r = await act.run<{ id: string }>('POST', '/v1/managed-properties', { ...f, country: country.code, ownership_evidence_ids: docs.map((d) => d.id) });
    if (r) router.replace(`/managed/${r.id}`);
  }

  return (
    <Screen ground="paper" back eyebrow="Property management" title="Register a property" footer={<Button title="Register the property" disabled={!ready} loading={act.busy} onPress={() => void register()} />}>
      <T v="callout" muted>Tenmina checks you own it and inspects its condition with photos. Rent is paid by the tenant into your own bank account, never to Tenmina.</T>
      <Field label="Name" value={f.title} onChange={set('title')} placeholder="For example: Family house in Kumasi" />
      <Field label="Town or area" value={f.locality} onChange={set('locality')} />
      <Field label="Address" value={f.address} onChange={set('address')} />
      <Field label="Region" value={f.region} onChange={set('region')} />
      <Field label="Digital address" value={f.ghana_post_gps} onChange={set('ghana_post_gps')} hint="If the property has one." />
      <Panel style={{ gap: space[2] }}>
        <Label>Proof that you own it</Label>
        <T v="callout">An indenture, land title or site plan in your name.</T>
        {docs.map((d, i) => (
          <FileRow key={d.id} id={d.id} name={d.original_name || 'Document'} type={d.content_type} detail="Stored and sealed" last={i === docs.length - 1} />
        ))}
        {me ? <AddFile label={docs.length ? 'Add another document from' : 'Add a document from'} variant={docs.length ? 'dark' : 'primary'} subject={{ type: 'pmg_owner_document', id: me.id, role: 'ownership', country: country.code, description: 'Proof of ownership' }} onDone={(ev) => setDocs((all) => [...all, ev])} /> : null}
      </Panel>
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
