'use client';
/* Report a repair (US-PMG-004): Tenmina collects at least two quotes from vetted contractors and the
   owner approves one. */
import { useState } from 'react';
import { Button, Card, Field, Input, ProblemBox, Select, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { EmptyText, FilePick, Loaded, PageHead, Section, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { uploadEvidence } from '@/components/roles/files';
import type { Tenancy } from '@/components/roles/tenancy';

type Repair = { id: string; property_title: string; title: string; description: string; urgent: boolean; status: string; quotes_needed: number; work_done_at: string | null; created_at: string };

const REPAIR_TEXT: Record<string, string> = {
  reported: 'Reported. Tenmina is asking contractors for quotes.', quoting: 'Collecting quotes.', quotes_ready: 'Quotes are with the owner.',
  approved: 'The owner approved a quote.', funded: 'The money is at the bank. The contractor will contact you.', in_progress: 'Work in progress.',
  inspected: 'Inspected.', paid: 'Done and paid.', closed: 'Closed.',
};

export default function TenantRepairs() {
  const ten = useGet<Page<Tenancy>>('/v1/tenancies');
  const q = useGet<Page<Repair>>('/v1/repairs');
  const api = useApi();
  const act = useAct();
  const [prop, setProp] = useState('');
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [urgent, setUrgent] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const tenancies = items(ten.data);
  const property = prop || tenancies[0]?.property || '';
  return (
    <div className="stack">
      <PageHead back={{ href: '/tenant', label: 'Tenancy' }} label="My home" title="Repairs">Tell Tenmina what needs fixing. You never pay a contractor yourself.</PageHead>
      <Section title="Report a repair">
        <Card className="stack">
          {tenancies.length > 1 ? <Field label="Property"><Select value={property} onChange={(e) => setProp(e.target.value)}>{tenancies.map((t) => <option key={t.id} value={t.property}>{t.property_title}</option>)}</Select></Field> : null}
          <Field label="What needs fixing"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Describe it"><Textarea value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
          <FilePick label="Photo" file={file} onFile={setFile} accept="image/*" />
          <label className="check-row" style={{ minHeight: 44 }}><input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} style={{ width: 22, height: 22 }} /> Urgent: water, power, safety or security</label>
          <Button variant="primary" disabled={!property || !title.trim() || !desc.trim() || !file} busy={act.busy === 'r'} onClick={() => act.run('r', async () => {
            const ev = await uploadEvidence(file!, { type: 'managed_property', id: property, role: 'repair_photo' });
            await api('POST', '/v1/repairs', { property_id: property, title, description: desc, photo_ids: [ev.id], urgent });
            setTitle(''); setDesc(''); setFile(null); await q.mutate();
          }, 'Reported. Tenmina will tell you what happens next.')}>Report the repair</Button>
          <ProblemBox error={act.error} />
        </Card>
      </Section>
      <Section title="Your repairs">
        <Loaded q={q}>{(d) => items(d).length ? items(d).map((r) => (
          <Card key={r.id} className="stack" style={{ gap: 4 }}>
            <div className="spread"><strong>{r.title}</strong><Status value={r.status} /></div>
            <span style={{ fontSize: 14 }}>{REPAIR_TEXT[r.status] ?? words(r.status)}</span>
            <span className="muted" style={{ fontSize: 13 }}>Reported <When value={r.created_at} />{r.urgent ? ' · urgent' : ''}</span>
          </Card>
        )) : <EmptyText>No repairs reported.</EmptyText>}</Loaded>
      </Section>
      {act.toast}
    </div>
  );
}
