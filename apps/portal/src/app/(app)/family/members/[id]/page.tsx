'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, Money, ProblemBox, Skeleton, Tabs, When, useGet, useSession } from '@tenmina/web-ui';
import { AcctCard, AcctRow, ActionDialog, EvidenceLink, PageHead, Proof, Section, list, useAction, words, type Any } from '@/components/kit';

/** W-28 · SCR-PTL-42: the family member's statement. Who was paid, where money is held, and receipts. */
export default function Member() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const router = useRouter();
  const m = useGet<Any>(`/v1/family-members/${id}`);
  const st = useGet<Any>(`/v1/family-members/${id}/statement`);
  const pdfs = useGet<Any[]>(`/v1/family-members/${id}/statement-pdfs`);
  const a = useAction();
  const [tab, setTab] = useState('statement');
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState<Any>(null);
  if (m.isLoading) return <Skeleton lines={6} />;
  if (!m.data) return <ProblemBox error={m.error} />;
  const fm = m.data;
  const s = st.data;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={words(fm.relationship)} title={fm.full_name} sub={[fm.address, fm.phone].filter(Boolean).join(' · ')}
        right={<Button variant="ghost" size="sm" onClick={() => { setF({ full_name: fm.full_name, phone: fm.phone, address: fm.address, may_confirm_visits: fm.may_confirm_visits }); setEdit(true); }}>Edit</Button>} />
      {fm.may_confirm_visits ? <Proof>May confirm care visits</Proof> : null}
      <div className="pt-chooser">
        <Link className="btn btn-primary" href={`/family/invoices/new?member=${id}`}>Add a bill</Link>
        <Link className="btn btn-ghost" href={`/family/care/new?member=${id}`}>Care visits</Link>
        <Link className="btn btn-ghost" href={`/family/errands/new?member=${id}`}>An errand</Link>
      </div>
      <Tabs current={tab} onChange={setTab} items={[{ key: 'statement', label: 'Statement' }, { key: 'pdf', label: 'Saved statements' }]} />
      {tab === 'statement' ? (st.isLoading ? <Skeleton /> : s ? (
        <div className="stack">
          {(s.held_at_bank ?? []).length ? (
            <Section title="Held at the bank">
              <AcctRow>
                {s.held_at_bank.map((h: Any) => <AcctCard key={h.escrow_id} href={`/property/escrows/${h.escrow_id}`} title="Held for your family" reference={h.escrow_reference} amount={h.held_at_bank} holder={me?.full_name ?? ''} note={`Ready to pay out: ${h.available_to_instruct.currency} ${h.available_to_instruct.amount}`} />)}
              </AcctRow>
              <p className="muted" style={{ margin: 0, fontSize: 14 }}>{s.note}</p>
              <Link className="btn btn-ghost" href={`/property/escrows/${s.held_at_bank[0].escrow_id}/pay-in`}>Add money</Link>
            </Section>
          ) : null}
          {(s.totals ?? []).map((t: Any) => (
            <div key={t.currency} className="card grid3" style={{ gap: 8 }}>
              <div><div className="label">Billed</div><Money value={{ amount: t.invoiced, currency: t.currency }} /></div>
              <div><div className="label">Paid</div><Money value={{ amount: t.paid, currency: t.currency }} /></div>
              <div><div className="label">Waiting</div><Money value={{ amount: t.awaiting_payment, currency: t.currency }} /></div>
            </div>
          ))}
          <Section title="Statement">
            {list(s.lines).length ? [...list(s.lines)].reverse().map((l: Any, i: number) => (
              <div key={`${l.type}-${l.id}-${i}`} className="card stack" style={{ gap: 4 }}>
                <div className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                  <div><div className="label"><When value={l.at} /> · {words(l.type)}</div><strong>{l.description}</strong><div className="muted" style={{ fontSize: 14 }}>{l.institution} · <span className="mono">{l.reference}</span>{l.route ? ` · ${l.route === 'held_funds' ? 'paid by the bank' : 'paid by you'}` : ''}</div></div>
                  {l.amount ? <Money value={l.amount} /> : null}
                </div>
                <div className="row">{l.type === 'invoice' ? <Link className="btn btn-ghost btn-sm" href={`/family/invoices/${l.id}`}>Open</Link> : l.type === 'payment' ? <Link className="btn btn-ghost btn-sm" href={`/family/fee-payments/${l.id}`}>Open</Link> : null}{l.evidence_id ? <EvidenceLink id={l.evidence_id} label="Receipt" /> : null}<span className="muted" style={{ fontSize: 13 }}>{words(l.status)}</span></div>
              </div>
            )) : <p className="muted">Nothing yet.</p>}
          </Section>
        </div>
      ) : <ProblemBox error={st.error} />) : (
        <Section title="Saved statements">
          {(pdfs.data ?? []).map((p: Any) => <div key={p.id} className="card spread"><span><When value={p.created_at} withTime /></span><EvidenceLink id={p.evidence} label="Download PDF" /></div>)}
          <Button variant="dark" busy={a.busy === 'pdf'} onClick={() => a.run('pdf', () => a.post(`/v1/family-members/${id}/statement-pdfs`), 'Statement saved', () => pdfs.mutate())}>Make a PDF of today&apos;s statement</Button>
        </Section>
      )}
      <ProblemBox error={a.error} />
      <ActionDialog open={edit} onClose={() => setEdit(false)} title="Edit" submit="Save" busy={a.busy === 'e'} error={a.error}
        onSubmit={() => a.run('e', () => a.post(`/v1/family-members/${id}`, f, 'PATCH'), 'Saved', () => { setEdit(false); m.mutate(); })}>
        {f ? <>
          <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Phone"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
          <Field label="Address"><Input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></Field>
          <label className="row" style={{ flexWrap: 'nowrap' }}><input type="checkbox" checked={f.may_confirm_visits} onChange={(e) => setF({ ...f, may_confirm_visits: e.target.checked })} style={{ width: 24, height: 24 }} /> May confirm care visits</label>
          <Button type="button" variant="ghost" onClick={() => a.run('rm', () => a.post(`/v1/family-members/${id}`, undefined, 'DELETE'), 'Removed', () => router.push('/family'))}>Remove from my family list</Button>
        </> : null}
      </ActionDialog>
      {a.toast}
    </div>
  );
}
