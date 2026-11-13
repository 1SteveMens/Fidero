'use client';
import { useParams } from 'next/navigation';
import { Chip, KV, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { EvidenceLink, Ink, PageHead, Proof, Section, words, type Any } from '@/components/kit';

/** One data protection request (FR-DPR-003): its due date, outcome, the export file and what is kept. */
export default function DataRequest() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any[]>('/v1/me/data-requests');
  const del = useGet<Any[]>('/v1/me/deletion-requests');
  const r = [...(q.data ?? []), ...(del.data ?? [])].find((x: Any) => x.id === id);
  if (q.isLoading) return <Ink><Skeleton /></Ink>;
  if (!r) return <Ink><ProblemBox error={q.error ?? new Error('We could not find that request.')} /></Ink>;
  return (
    <Ink>
      <PageHead back={{ href: '/account/privacy', label: 'Privacy and my data' }} label={`${words(r.type)} request`} title={r.status === 'completed' ? 'Done' : words(r.status)} sub={r.details} />
      {r.status === 'completed' ? <Proof>Completed <When value={r.completed_at} /></Proof> : <Chip>Due <When value={r.due_on} /></Chip>}
      <KV items={[['Asked', <When key="c" value={r.created_at} />], ['Due', <When key="d" value={r.due_on} />], ['Rejected because', r.rejection_reason || '—']]} />
      {r.export_evidence ? <div className="card stack"><EvidenceLink id={r.export_evidence} label="Download your data" /><span className="mono muted" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>SHA-256 {r.export_sha256}</span></div> : null}
      {(r.corrections ?? []).length ? <Section title="Corrected">{r.corrections.map((c: Any, i: number) => <div key={i} className="card">{words(c.field)} · <When value={c.at} /></div>)}</Section> : null}
      {(r.kept_statement ?? []).length ? <Section title="Kept, and why">{r.kept_statement.map((k: Any, i: number) => <div key={i} className="card"><strong>{k.what}</strong><div className="muted">{k.why}</div><div className="mono" style={{ fontSize: 12 }}>Until {k.until}</div></div>)}</Section> : null}
      {(r.open_matters ?? []).length ? <Section title="Still open">{r.open_matters.map((m: Any, i: number) => <div key={i} className="card"><strong>{m.title}</strong><div className="muted">{m.reason}</div></div>)}</Section> : null}
    </Ink>
  );
}
