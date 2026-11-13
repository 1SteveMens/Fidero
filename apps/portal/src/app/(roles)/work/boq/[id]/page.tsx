'use client';
/* Bill of quantities review (US-BLD-002): the quantity surveyor uploads the signed bill, lists the items
   and sets the milestone split. The split must add up to 100%. The client approves the budget after. */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Field, Input, Money, ProblemBox, Skeleton, Status, Table, Textarea, When, useGet } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { EvidenceLink, FilePick, PageHead, Section, useAct, useApi } from '@/components/roles/kit';
import { uploadEvidence } from '@/components/roles/files';

type Boq = { id: string; version: number; items: { description: string; quantity?: string; unit?: string; rate?: string; amount?: string }[]; split: { key: string; name: string; share_pct: string }[]; total: MoneyT; status: string; evidence_id: string | null; accepted_at: string | null; note: string; created_at: string };
type Project = { id: string; title: string; status: string; budget: MoneyT | null; country: string };
type Line = { description: string; quantity: string; unit: string; rate: string };

export default function BoqPage() {
  const { id } = useParams<{ id: string }>();
  const p = useGet<Project>(`/v1/projects/${id}`);
  const q = useGet<Boq[]>(`/v1/projects/${id}/boq`);
  const api = useApi();
  const act = useAct();
  const latest = q.data?.[0];
  const [lines, setLines] = useState<Line[]>([{ description: '', quantity: '1', unit: '', rate: '' }]);
  const [split, setSplit] = useState<{ key: string; name: string; share_pct: string }[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState('');
  if (p.isLoading || q.isLoading) return <Skeleton lines={6} />;
  if (p.error) return <ProblemBox error={p.error} />;
  const shares = split ?? latest?.split ?? [];
  const sum = shares.reduce((a, s) => a + (Number(s.share_pct) || 0), 0);
  const total = lines.reduce((a, l) => a + (Number(l.quantity) || 0) * (Number(l.rate) || 0), 0);
  const ready = file && lines.every((l) => l.description.trim() && Number(l.rate) > 0) && (!shares.length || Math.abs(sum - 100) < 0.01);

  return (
    <div className="stack">
      <PageHead back={{ href: '/work/boq', label: 'Bills of quantities' }} label="Bill of quantities" title={p.data?.title ?? 'Project'} />
      {latest ? (
        <Section title={`Current bill, version ${latest.version}`}>
          <Card className="stack">
            <div className="spread"><Status value={latest.status} /><Money value={latest.total} /></div>
            <Table rows={latest.items.map((x, n) => ({ id: String(n), ...x }))} columns={[
              { key: 'd', label: 'Item', render: (r) => r.description },
              { key: 'q', label: 'Qty', render: (r) => `${r.quantity ?? ''} ${r.unit ?? ''}` },
              { key: 'a', label: 'Amount', render: (r) => r.amount ?? '—' },
            ]} />
            <div className="label">Milestone split</div>
            {latest.split.map((s) => <div key={s.key} className="statline"><span>{s.name}</span><span className="v">{s.share_pct}%</span></div>)}
            <div className="row"><EvidenceLink id={latest.evidence_id} label="Signed bill" />{latest.accepted_at ? <span className="muted">Accepted <When value={latest.accepted_at} /></span> : null}</div>
          </Card>
        </Section>
      ) : null}
      <Section title={latest ? 'Upload a new version' : 'Upload the bill'}>
        <Card className="stack">
          <FilePick label="Signed bill of quantities (PDF)" file={file} onFile={setFile} accept="application/pdf,image/*" />
          {lines.map((l, n) => (
            <div key={n} className="stack" style={{ gap: 6, borderTop: n ? '1px solid var(--color-line)' : 0, paddingTop: n ? 10 : 0 }}>
              <Field label={`Item ${n + 1}`}><Input value={l.description} onChange={(e) => setLines(lines.map((x, i) => i === n ? { ...x, description: e.target.value } : x))} /></Field>
              <div className="grid2" style={{ gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                <Field label="Qty"><Input inputMode="decimal" value={l.quantity} onChange={(e) => setLines(lines.map((x, i) => i === n ? { ...x, quantity: e.target.value } : x))} /></Field>
                <Field label="Unit"><Input value={l.unit} onChange={(e) => setLines(lines.map((x, i) => i === n ? { ...x, unit: e.target.value } : x))} /></Field>
                <Field label="Rate"><Input inputMode="decimal" value={l.rate} onChange={(e) => setLines(lines.map((x, i) => i === n ? { ...x, rate: e.target.value } : x))} /></Field>
              </div>
            </div>
          ))}
          <div className="row">
            <Button variant="ghost" size="sm" onClick={() => setLines([...lines, { description: '', quantity: '1', unit: '', rate: '' }])}>Add item</Button>
            {lines.length > 1 ? <Button variant="ghost" size="sm" onClick={() => setLines(lines.slice(0, -1))}>Remove last</Button> : null}
          </div>
          <div className="statline"><span>Total</span><span className="v">{total.toLocaleString('en-GB', { minimumFractionDigits: 2 })} {p.data?.budget?.currency ?? ''}</span></div>
          {shares.length ? (
            <>
              <div className="label">Milestone split (must add up to 100%)</div>
              {shares.map((s, n) => (
                <div key={s.key} className="spread"><span>{s.name}</span><Input style={{ width: 100 }} inputMode="decimal" aria-label={`${s.name} share`} value={s.share_pct} onChange={(e) => setSplit(shares.map((x, i) => i === n ? { ...x, share_pct: e.target.value } : x))} /></div>
              ))}
              <div className="statline"><span>Adds up to</span><span className="v">{sum}%</span></div>
            </>
          ) : <p className="muted">The country's standard split applies.</p>}
          <Field label="Note"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Button variant="primary" disabled={!ready} busy={act.busy === 's'} onClick={() => act.run('s', async () => {
            const ev = await uploadEvidence(file!, { type: 'bld_project', id, role: 'boq' });
            await api('POST', `/v1/projects/${id}/boq`, {
              items: lines.map((l) => ({ description: l.description, quantity: l.quantity, unit: l.unit, rate: l.rate, amount: ((Number(l.quantity) || 0) * (Number(l.rate) || 0)).toFixed(2) })),
              ...(shares.length ? { split: shares.map((s) => ({ key: s.key, name: s.name, share_pct: s.share_pct })) } : {}),
              evidence_ids: [ev.id], note,
            });
            setFile(null); await q.mutate();
          }, 'Bill uploaded. The client approves the budget next.')}>Send the bill</Button>
          <ProblemBox error={act.error} />
        </Card>
      </Section>
      {act.toast}
    </div>
  );
}
