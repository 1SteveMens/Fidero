'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Field, Input, KV, Money, NeedsYou, ProblemBox, Select, Skeleton, Textarea, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, Bar, EvidenceLink, PageHead, Proof, Section, Upload, list, useAction, useCountry, words, type Any } from '@/components/kit';

const VENDOR_KINDS = ['caterer', 'tent_and_chairs', 'funeral_home', 'printer', 'decorator', 'sound', 'transport', 'venue', 'other'];

/** SCR-PTL-53: an event with its budget, verified vendors and vendor payments against invoices and delivery proof. */
export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const country = useCountry();
  const q = useGet<Any>(`/v1/events/${id}`);
  const pays = useGet<Any[]>(`/v1/events/${id}/vendor-payments`);
  const rec = useGet<Any[]>(`/v1/events/${id}/receipts`);
  const fams = useGet<Any>('/v1/family-members');
  const a = useAction();
  const [dlg, setDlg] = useState<null | 'vendor' | 'pay' | 'budget' | 'confirmer' | 'cancel'>(null);
  const [v, setV] = useState({ kind: 'caterer', name: '', registration_number: '', contact_name: '', contact_phone: '', quote: '' });
  const [quoteEv, setQuoteEv] = useState<Any>(null);
  const [p, setP] = useState({ vendor_id: '', kind: 'deposit', amount: '', description: '' });
  const [b, setB] = useState({ amount: '', reason: '' });
  const [fm, setFm] = useState('');
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const e = q.data;
  const bva = e.budget_vs_actual;
  const cur = e.budget?.currency || country.currency;
  const refresh = () => { q.mutate(); pays.mutate(); rec.mutate(); };
  const done = () => { setDlg(null); refresh(); };
  const verified = (e.vendors ?? []).filter((x: Any) => x.status === 'verified');
  const waiting = (pays.data ?? []).filter((x: Any) => x.status === 'evidenced');
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={`${words(e.kind)} · ${words(e.status)}`} title={e.name} sub={<><When value={e.event_date} /> · {e.locality}</>} />
      {waiting.map((x: Any) => <NeedsYou key={x.id} title={`Approve ${x.amount.currency} ${x.amount.amount} to ${x.vendor_name}`} detail={`${words(x.kind)}: ${x.description}. Nothing is paid until you approve.`} href={`/family/vendor-payments/${x.id}`} />)}
      {(e.warnings ?? []).map((w: Any, i: number) => <div key={i} className="card">{w.message ?? String(w)}</div>)}
      {bva ? (
        <section className="card stack">
          <div className="spread"><strong>Budget</strong><Money value={bva.budget} /></div>
          <Bar value={Number(bva.paid.amount)} max={Number(bva.budget.amount)} label="Paid against the budget" />
          <KV items={[['Quotes', <Money key="q" value={bva.quotes} />], ['Committed', <Money key="c" value={bva.committed} />], ['Paid', <Money key="p" value={bva.paid} />], ['Left', <Money key="l" value={bva.remaining} />]]} />
          <Button variant="ghost" size="sm" onClick={() => setDlg('budget')}>Change the budget</Button>
        </section>
      ) : null}
      {e.escrow ? (
        <Link href={`/property/escrows/${e.escrow}`} className="card card-link"><div className="label">Held at the bank · {e.escrow_reference}</div><div>{words(e.escrow_status)}. Open to pay in or see the account.</div></Link>
      ) : verified.length ? (
        <Button variant="primary" busy={a.busy === 'esc'} onClick={() => a.run('esc', () => a.post(`/v1/events/${id}/escrow`), 'The bank escrow is open', refresh)}>Open the bank escrow for the budget</Button>
      ) : <p className="muted" style={{ margin: 0 }}>Add vendors. Once one is verified, the budget goes to the bank.</p>}
      {e.fee_order_id ? <Link className="btn btn-ghost" href={`/property/orders/${e.fee_order_id}`}>Tenmina&apos;s fee for this event</Link> : null}
      <KV items={[['Confirms deliveries', e.confirmer?.name ?? 'Nobody yet']]} />
      <Button variant="ghost" size="sm" onClick={() => setDlg('confirmer')}>Choose who confirms deliveries</Button>
      <Section title="Vendors" action={<Button variant="ghost" size="sm" onClick={() => setDlg('vendor')}>Add</Button>}>
        {(e.vendors ?? []).map((x: Any) => (
          <div key={x.id} className="card spread">
            <div><div className="label">{words(x.kind)}</div><strong>{x.name}</strong><div className="muted" style={{ fontSize: 14 }}>Quote <Money value={x.quote} />{x.payee?.account_last4 ? ` · account ending ${x.payee.account_last4}` : ''}</div></div>
            {x.status === 'verified' ? <Proof>Verified</Proof> : <Chip>{words(x.status)}</Chip>}
          </div>
        ))}
      </Section>
      <Section title="Payments" action={verified.length && e.escrow ? <Button variant="ghost" size="sm" onClick={() => setDlg('pay')}>Pay a vendor</Button> : undefined}>
        {(pays.data ?? []).map((x: Any) => <Link key={x.id} href={`/family/vendor-payments/${x.id}`} className="card card-link spread"><span>{x.vendor_name} · {words(x.kind)}<div className="muted" style={{ fontSize: 14 }}>{words(x.status)}</div></span><Money value={x.amount} /></Link>)}
      </Section>
      {(rec.data ?? []).length ? (
        <Section title="Receipts">
          {(rec.data ?? []).map((r: Any) => <div key={r.payment_id} className="card stack" style={{ gap: 4 }}><div className="spread"><span>Paid to {r.paid_to}, account ending {r.account_last4}</span><Money value={r.amount} /></div><div className="mono muted" style={{ fontSize: 12 }}><When value={r.paid_at} /> · bank reference {r.bank_reference}</div><div className="row">{(r.evidence_ids ?? []).map((ev: string) => <EvidenceLink key={ev} id={ev} label="Proof" variant="preview" />)}</div></div>)}
        </Section>
      ) : null}
      <ProblemBox error={a.error} />
      {['planning', 'funded', 'in_progress'].includes(e.status) ? (
        <div className="row">
          {e.status === 'in_progress' ? <Button variant="ghost" busy={a.busy === 'close'} onClick={() => a.run('close', () => a.post(`/v1/events/${id}/close`), 'Closed', refresh)}>Close the event</Button> : null}
          <Button variant="ghost" onClick={() => setDlg('cancel')}>Cancel the event</Button>
        </div>
      ) : null}

      <ActionDialog open={dlg === 'vendor'} onClose={() => setDlg(null)} title="Add a vendor" submit="Add and ask Tenmina to check it" busy={a.busy === 'v'} error={a.error}
        onSubmit={() => a.run('v', () => a.post(`/v1/events/${id}/vendors`, { kind: v.kind, name: v.name, registration_number: v.registration_number, contact_name: v.contact_name, contact_phone: v.contact_phone, quote: v.quote ? { amount: v.quote, currency: cur } : undefined, quote_evidence_id: quoteEv?.id }), 'Added', done)}>
        <Field label="What they do"><Select value={v.kind} onChange={(ev) => setV({ ...v, kind: ev.target.value })}>{VENDOR_KINDS.map((k) => <option key={k} value={k}>{words(k)}</option>)}</Select></Field>
        <Field label="Business name"><Input value={v.name} onChange={(ev) => setV({ ...v, name: ev.target.value })} required /></Field>
        <Field label="Registration number (if known)"><Input value={v.registration_number} onChange={(ev) => setV({ ...v, registration_number: ev.target.value })} /></Field>
        <Field label="Contact name"><Input value={v.contact_name} onChange={(ev) => setV({ ...v, contact_name: ev.target.value })} /></Field>
        <Field label="Contact phone"><Input type="tel" value={v.contact_phone} onChange={(ev) => setV({ ...v, contact_phone: ev.target.value })} /></Field>
        <Field label={`Their quote (${cur})`}><Input inputMode="decimal" value={v.quote} onChange={(ev) => setV({ ...v, quote: ev.target.value.replace(/[^\d.]/g, '') })} /></Field>
        <Upload subject={{ type: 'evt_event', id, role: 'quote' }} label={quoteEv ? 'Quote attached' : 'Attach the quote'} onDone={setQuoteEv} />
      </ActionDialog>
      <ActionDialog open={dlg === 'pay'} onClose={() => setDlg(null)} title="Pay a vendor" submit="Propose the payment" busy={a.busy === 'p'} error={a.error}
        onSubmit={() => a.run('p', () => a.post<Any>(`/v1/events/${id}/vendor-payments`, { vendor_id: p.vendor_id, kind: p.kind, amount: { amount: p.amount, currency: cur }, description: p.description }), undefined, (r) => router.push(`/family/vendor-payments/${r.id}`))}>
        <Field label="Vendor (verified only)"><Select value={p.vendor_id} onChange={(ev) => setP({ ...p, vendor_id: ev.target.value })} required><option value="">Choose</option>{verified.map((x: Any) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
        <Field label="Which payment"><Select value={p.kind} onChange={(ev) => setP({ ...p, kind: ev.target.value })}><option value="deposit">Deposit</option><option value="balance">Balance</option><option value="full">Full payment</option></Select></Field>
        <Field label={`Amount (${cur})`}><Input inputMode="decimal" value={p.amount} onChange={(ev) => setP({ ...p, amount: ev.target.value.replace(/[^\d.]/g, '') })} required /></Field>
        <Field label="What for"><Input value={p.description} onChange={(ev) => setP({ ...p, description: ev.target.value })} /></Field>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>A balance is paid only against the vendor&apos;s invoice and proof of delivery.</p>
      </ActionDialog>
      <ActionDialog open={dlg === 'budget'} onClose={() => setDlg(null)} title="Change the budget" submit="Save" busy={a.busy === 'b'} error={a.error}
        onSubmit={() => a.run('b', () => a.post(`/v1/events/${id}/budget`, { budget: { amount: b.amount, currency: cur }, reason: b.reason }), 'Saved', done)}>
        <Field label={`New budget (${cur})`}><Input inputMode="decimal" value={b.amount} onChange={(ev) => setB({ ...b, amount: ev.target.value.replace(/[^\d.]/g, '') })} required /></Field>
        <Field label="Why"><Textarea value={b.reason} onChange={(ev) => setB({ ...b, reason: ev.target.value })} required /></Field>
      </ActionDialog>
      <ActionDialog open={dlg === 'confirmer'} onClose={() => setDlg(null)} title="Who confirms deliveries" submit="Save" busy={a.busy === 'cf'} error={a.error}
        onSubmit={() => a.run('cf', () => a.post(`/v1/events/${id}/confirmer`, { family_member_id: fm }, 'PUT'), 'Saved', done)}>
        <Field label="Family member at the event"><Select value={fm} onChange={(ev) => setFm(ev.target.value)} required><option value="">Choose</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>They get a code on their own phone to confirm each delivery.</p>
      </ActionDialog>
      <ActionDialog open={dlg === 'cancel'} onClose={() => setDlg(null)} title="Cancel the event" submit="Cancel the event" busy={a.busy === 'x'} error={a.error}
        onSubmit={() => a.run('x', () => a.post(`/v1/events/${id}/cancel`, { reason }), 'Cancelled', done)}>
        <Field label="Why"><Textarea value={reason} onChange={(ev) => setReason(ev.target.value)} required /></Field>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>Money not yet paid goes back from the bank to the account it came from.</p>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
