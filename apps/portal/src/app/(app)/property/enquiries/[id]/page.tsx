'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Button, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import { PageHead, useAction, words, type Any } from '@/components/kit';

/** An enquiry about a listing or a wanted plot, and Tenmina's answer. */
export default function Enquiry() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Any>(`/v1/enquiries/${id}`);
  const a = useAction();
  if (q.isLoading) return <Skeleton lines={4} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const e = q.data;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${e.reference} · ${words(e.status)}`} title="Your question" />
      <div className="msg mine" style={{ alignSelf: 'stretch', maxWidth: '100%' }}>
        <div className="label" style={{ color: 'inherit', opacity: 0.7 }}>You · <When value={e.created_at} withTime /></div>
        {e.message}
        {e.wanted_locality || e.budget ? <div style={{ fontSize: 14, opacity: 0.8 }}>{[e.wanted_locality, e.wanted_region].filter(Boolean).join(', ')}{e.budget ? <> · budget <Money value={e.budget} /></> : null}</div> : null}
      </div>
      {e.answer ? (
        <div className="msg">
          <div className="label">Tenmina · <When value={e.answered_at} withTime /></div>
          {e.answer}
        </div>
      ) : <p className="muted">Tenmina will answer here and in your inbox.</p>}
      {e.listing_id ? <Link className="btn btn-ghost" href={`/property/listings/${e.listing_id}`}>Open the listing</Link> : <Link className="btn btn-ghost" href="/property/listings">See checked plots</Link>}
      {e.status !== 'closed' ? <Button variant="ghost" busy={!!a.busy} onClick={() => a.run('close', () => a.post(`/v1/enquiries/${id}/closures`, { reason: 'Closed by the buyer' }), 'Closed', () => q.mutate())}>I have my answer, close it</Button> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}
