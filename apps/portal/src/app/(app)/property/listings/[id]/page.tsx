'use client';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Field, KV, Money, ProblemBox, Skeleton, Textarea, Verdict, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, PageHead, Section, useAction, words, type Any } from '@/components/kit';

/** W-22 · SCR-PTL-27: listing detail with the badge, the full report, the seller's track record; reserve (SCR-PTL-28). */
export default function ListingDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const q = useGet<Any>(`/v1/listings/${id}`);
  const rep = useGet<Any>(q.data?.badge ? `/v1/listings/${id}/report` : null, undefined, { shouldRetryOnError: false });
  const a = useAction();
  const [ask, setAsk] = useState(false);
  const [msg, setMsg] = useState('');
  const [reserve, setReserve] = useState(false);
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const x = q.data;
  const tr = x.seller_track_record;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/property/listings', label: 'Checked plots' }} label={`${words(x.kind)} · ${x.reference}`} title={x.title} sub={x.locality} />
      {x.media?.length ? (
        <div className="acct-row">{x.media.map((m: Any) => <img key={m.id} src={m.url} alt={m.caption || x.title} style={{ width: '100%', aspectRatio: '4 / 3', objectFit: 'cover', borderRadius: 20, background: 'var(--color-surface-2)' }} />)}</div>
      ) : null}
      <div className="spread"><Money value={x.price} className="h2" />{x.reserved ? <Chip>Reserved</Chip> : null}</div>
      {x.badge ? (
        <section className="card stack" style={{ gap: 6 }}>
          <Chip tone="lime">✓ {x.badge.label}</Chip>
          <div>Checked <When value={x.badge.checks_date} />. The badge lasts until <When value={x.badge.expires_at} />.</div>
          {rep.data ? <div className="row"><Verdict value={rep.data.verdict} /><span className="mono">{rep.data.reference}</span></div> : null}
        </section>
      ) : <p className="muted">This listing has no current badge.</p>}
      {x.description ? <p style={{ margin: 0 }}>{x.description}</p> : null}
      <KV items={[['Size', x.size_sqm ? `${Number(x.size_sqm).toLocaleString('en-GB')} m²` : '—'], ['Estate', x.estate_name || '—'], ['Seller', x.seller?.name]]} />
      {rep.data ? (
        <Section title="The full report">
          {(rep.data.sections ?? []).filter((s: Any) => s.verdict).map((s: Any) => (
            <div key={s.number} className="spread card" style={{ flexWrap: 'nowrap' }}><span><span className="mono muted">{s.label}</span> {s.title}<div className="muted" style={{ fontSize: 13 }}>{s.findings}</div></span><Verdict value={s.verdict} /></div>
          ))}
          {rep.data.pdf?.url ? <a className="btn btn-ghost" href={rep.data.pdf.url} target="_blank" rel="noopener noreferrer">Download the report PDF</a> : null}
          <div className="mono muted" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>SHA-256 {rep.data.pdf_sha256}</div>
        </Section>
      ) : null}
      {tr ? (
        <Section title="Seller's track record">
          <div className="card">{tr.enough_history ? <KV items={[['Deals completed', tr.deals_completed], ['Disputes lost', tr.disputes_lost], ['Average rating', tr.average_score ?? '—']]} /> : tr.summary}</div>
        </Section>
      ) : null}
      <p className="muted" style={{ fontSize: 14, margin: 0 }}>{x.disclosure}</p>
      <ProblemBox error={a.error} />
      <div className="stack">
        {x.can_reserve ? <Button variant="primary" onClick={() => setReserve(true)}>Reserve this plot</Button> : null}
        <Button variant="ghost" onClick={() => setAsk(true)}>Ask a question</Button>
      </div>
      <ActionDialog open={reserve} onClose={() => setReserve(false)} title="Reserve this plot" submit="Reserve" busy={a.busy === 'res'} error={a.error}
        onSubmit={() => a.run('res', () => a.post<Any>(`/v1/listings/${id}/reservations`), undefined, (r) => router.push(`/property/reservations/${r.id}`))}>
        <p style={{ margin: 0 }}>Reserving holds the plot for you while Tenmina runs a fresh search at the registry. An escrow is proposed: the bank holds the price and pays the seller only on proof, after you approve.</p>
      </ActionDialog>
      <ActionDialog open={ask} onClose={() => setAsk(false)} title="Ask about this plot" submit="Send" busy={a.busy === 'ask'} error={a.error} disabled={!msg.trim()}
        onSubmit={() => a.run('ask', () => a.post<Any>(`/v1/listings/${id}/enquiries`, { message: msg }), undefined, (e) => router.push(`/property/enquiries/${e.id}`))}>
        <Field label="Your question"><Textarea value={msg} onChange={(e) => setMsg(e.target.value)} /></Field>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>Tenmina answers. Your contact details are not given to the seller.</p>
      </ActionDialog>
    </div>
  );
}
