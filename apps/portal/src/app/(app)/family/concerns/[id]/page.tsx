'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Chip, KV, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { EvidenceLink, PageHead, words, type Any } from '@/components/kit';

/** A concern a carer raised (FR-CARE-006): what was seen, who was told and what was done. */
export default function Concern() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/concerns/${id}`);
  if (q.isLoading) return <Skeleton lines={5} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const c = q.data;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: `/family/care/${c.plan}`, label: 'Care plan' }} label={`${c.reference} · ${words(c.status)}`} title={`${words(c.kind)} concern about ${c.family_member?.full_name ?? ''}`} />
      <Chip>{words(c.severity)} severity</Chip>
      {c.narrative ? <p style={{ margin: 0 }}>{c.narrative}</p> : null}
      <KV items={[
        ['Raised', <When key="r" value={c.raised_at} withTime />],
        ['Told you', c.client_notified_at ? <When key="n" value={c.client_notified_at} withTime /> : '—'],
        ['A reviewer', c.routed_to_reviewer ? 'Is looking at it' : '—'],
        ['Acknowledged', c.acknowledged_at ? <When key="a" value={c.acknowledged_at} withTime /> : '—'],
        ['What was done', c.action_taken || '—'],
        ['Outcome for you', c.client_outcome || '—'],
        ['Closed', c.closed_at ? <When key="c" value={c.closed_at} withTime /> : '—'],
      ]} />
      {c.evidence ? <EvidenceLink id={c.evidence} label="Photo or file" variant="preview" /> : null}
      {c.visit ? <Link className="btn btn-ghost" href={`/family/visits/${c.visit}`}>The visit</Link> : null}
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>A Tenmina reviewer handles every concern and tells you what was done. In an emergency, call the family member and local emergency services first.</p>
    </div>
  );
}
