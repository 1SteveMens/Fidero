'use client';
/* Records confirmation for authority representatives (SCR-PTL-35, US-REC-004): allocations Tenmina captured
   from your books. Confirm what is right; say what is wrong. Only your own authority's records show. */
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, KV, ProblemBox, Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, EvidenceLink, Loaded, PageHead, Section, items, useAct, useApi, words, type Page } from '@/components/roles/kit';

type Authority = { id: string; name: string; kind: string; region: string; district: string; status: string };
type Allocation = {
  id: string; authority_name: string; reference: string; allottee_name: string; allocated_on: string; area_sqm: string | null; locality: string; plot_number: string;
  document_evidence: string | null; document_sha256: string; status: string; status_note: string; confirmed_name: string; confirmed_at: string | null;
  overlaps: { id: string; other_reference: string; other_authority: string; status: string }[]; previous: string | null;
};

export default function AuthorityRecords() {
  const auth = useGet<Page<Authority>>('/v1/records/authorities');
  const [qtext, setQ] = useState('');
  const q = useGet<Page<Allocation>>('/v1/records/allocations', qtext ? { q: qtext } : undefined);
  const all = items(q.data);
  const toConfirm = all.filter((a) => a.status === 'captured');
  const rest = all.filter((a) => a.status !== 'captured');
  return (
    <div className="stack">
      <PageHead label="Records" title={items(auth.data)[0]?.name ?? 'Your records'}>Allocations from your books, entered by Tenmina. Confirm each one you agree with.</PageHead>
      <Field label="Find a record"><Input value={qtext} onChange={(e) => setQ(e.target.value)} placeholder="Reference, name, locality or plot" /></Field>
      <Loaded q={q}>{() => (
        <>
          <Section title="To confirm">{toConfirm.length ? toConfirm.map((a) => <AllocationCard key={a.id} a={a} onDone={() => q.mutate()} />) : <EmptyText>Nothing waiting for you.</EmptyText>}</Section>
          <Section title="Other records">{rest.length ? rest.map((a) => <AllocationCard key={a.id} a={a} onDone={() => q.mutate()} />) : <EmptyText>No other records.</EmptyText>}</Section>
        </>
      )}</Loaded>
    </div>
  );
}

function AllocationCard({ a, onDone }: { a: Allocation; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [reason, setReason] = useState('');
  const openOverlaps = a.overlaps.filter((o) => o.status === 'open');
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label">{a.reference}</div><strong>{a.allottee_name}</strong></div>{a.status === 'confirmed' ? <Chip tone="lime">✓ Confirmed</Chip> : <Status value={a.status} needsYou={a.status === 'captured'} />}</div>
      <KV items={[['Allocated', <When key="d" value={a.allocated_on} />], ['Where', [a.locality, a.plot_number && `plot ${a.plot_number}`].filter(Boolean).join(', ') || '—'], ['Area', a.area_sqm ? `${Number(a.area_sqm).toLocaleString('en-GB')} m²` : '—'], ['Confirmed', a.confirmed_at ? <span key="c">{a.confirmed_name}, <When value={a.confirmed_at} /></span> : '—']]} />
      {a.status_note ? <span style={{ fontSize: 14 }}>Note: {a.status_note}</span> : null}
      {openOverlaps.length ? <div className="banner-info">Overlaps {openOverlaps.map((o) => `${o.other_reference} (${o.other_authority})`).join(', ')}. Tenmina reviews overlaps before you can confirm.</div> : null}
      <EvidenceLink id={a.document_evidence} label="Copy of the book page" />
      {a.status === 'captured' ? (
        <>
          <Button variant="action" busy={act.busy === 'c'} disabled={openOverlaps.length > 0} onClick={() => act.run('c', async () => { await api('POST', `/v1/records/allocations/${a.id}/confirm`); onDone(); }, 'Confirmed in your name.')}>This record is right</Button>
          <Field label="Or say what is wrong"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <Button variant="ghost" disabled={!reason.trim()} busy={act.busy === 'd'} onClick={() => act.run('d', async () => { await api('POST', `/v1/records/allocations/${a.id}/dispute`, { reason }); onDone(); }, 'Recorded. Tenmina will correct it with you.')}>This record is wrong</Button>
        </>
      ) : a.status === 'confirmed' ? (
        <>
          <Field label="Something changed? Say what"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <Button variant="ghost" disabled={!reason.trim()} busy={act.busy === 'd'} onClick={() => act.run('d', async () => { await api('POST', `/v1/records/allocations/${a.id}/dispute`, { reason }); onDone(); }, 'Recorded.')}>Report a problem</Button>
        </>
      ) : <span className="muted" style={{ fontSize: 14 }}>{words(a.status)}: Tenmina is working on it.</span>}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
