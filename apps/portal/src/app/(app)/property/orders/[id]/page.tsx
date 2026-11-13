'use client';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { Button, Field, Input, KV, Money, ProblemBox, Select, Skeleton, Steps, When, call, useGet, useSession } from '@tenmina/web-ui';
import { FilePick, Ink, PageHead, Proof, RadioCard, postForm, useAction, words, type Any } from '@/components/kit';
import { PlotDrawer, type LngLat } from '@/components/plot-drawer';
import { orderSteps } from '@/lib/steps';

const LEAD_LABELS: Record<string, string> = { association: 'An association or church', webinar: 'A webinar or talk', referral: 'A friend or family member', remittance_partner: 'A money transfer service', other: 'Somewhere else' };

function Wizard() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const { me } = useSession();
  const q = useGet<Any>(`/v1/orders/${id}`);
  const o = q.data;
  const stepParam = Number(sp.get('step') || 0);
  const step = !o ? 0 : o.status === 'draft' ? (stepParam >= 2 && stepParam <= 4 ? stepParam : 2) : 5;
  const go = (n: number) => router.push(`/property/orders/${id}?step=${n}`);
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !o) return <ProblemBox error={q.error} />;
  const isLand = o.product_line !== 'event' && o.kind === 'verification';
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/property', label: 'Property' }} label={`${o.reference} · ${o.product_name}`}
        title={step === 2 ? (o.asset?.type === 'building' ? 'The building' : 'The plot') : step === 3 ? 'Documents and seller' : step === 4 ? 'Check and agree' : o.status === 'paid' ? 'Paid. Your case is open.' : o.status === 'cancelled' ? 'Order cancelled' : "Pay Tenmina's fee"} />
      {isLand ? <Steps items={orderSteps(Math.min(step - 1, 4)).map((s) => ({ ...s, state: o.status === 'paid' ? 'done' : s.state }))} /> : null}
      {step === 2 ? <PlotStep o={o} onSaved={() => { q.mutate(); go(3); }} country={me?.home_country || 'GH'} /> : null}
      {step === 3 ? <DocsStep o={o} onBack={() => go(2)} onSaved={() => { q.mutate(); go(4); }} /> : null}
      {step === 4 ? <AgreeStep o={o} onBack={() => go(3)} onDone={() => q.mutate()} /> : null}
      {step === 5 ? <PayStep o={o} refresh={() => q.mutate()} /> : null}
    </div>
  );
}

/** W-04 · SCR-PTL-07: locality, plot number, site plan reference, Ghana Post GPS, and a drawing. */
function PlotStep({ o, onSaved, country }: { o: Any; onSaved: () => void; country: string }) {
  const [f, setF] = useState({ type: o.asset?.type || 'plot', locality: o.asset?.locality || '', plot_number: o.asset?.plot_number || '', site_plan_ref: o.asset?.site_plan_ref || '', ghana_post_gps: o.asset?.ghana_post_gps || '' });
  const [points, setPoints] = useState<LngLat[]>(o.details?.drawn_points ?? []);
  const [centre, setCentre] = useState<LngLat | null>(o.details?.drawn_centre ?? null);
  const [gpsMsg, setGpsMsg] = useState('');
  const a = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  async function findGps() {
    setGpsMsg('');
    const r = await a.run('gps', () => call<Any>(a.client, 'GET', `/v1/geo/ghana-post/${encodeURIComponent(f.ghana_post_gps.trim())}`, undefined, { country }).catch(() => null));
    if (r?.location) { setCentre(r.location); setGpsMsg(r.message || 'Found.'); } else setGpsMsg(r?.message || 'We could not find that address. You can still draw from where you are.');
  }
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); a.run('save', () => a.post(`/v1/orders/${o.id}`, { asset: f, details: { ...(o.details || {}), drawn_points: points.length > 2 ? points : undefined, drawn_centre: centre ?? undefined } }, 'PATCH'), undefined, onSaved); }}>
      <Field label="Land or building"><Select value={f.type} onChange={set('type')}><option value="plot">Land (a plot)</option><option value="building">A building</option></Select></Field>
      <Field label="Town or area" hint="For example: Kasoa, Ofaakor"><Input value={f.locality} onChange={set('locality')} required /></Field>
      {f.type === 'plot' ? <>
        <Field label="Plot number" hint="As on the site plan or the seller's papers"><Input value={f.plot_number} onChange={set('plot_number')} /></Field>
        <Field label="Site plan reference" hint="The number on the site plan, if it has one"><Input value={f.site_plan_ref} onChange={set('site_plan_ref')} /></Field>
      </> : null}
      <Field label="Ghana Post GPS address" hint="For example: GA-123-4567. Optional, but it helps the surveyor find the place."><Input value={f.ghana_post_gps} onChange={set('ghana_post_gps')} /></Field>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Draw the plot (optional)</h3>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>A sketch helps the surveyor. The report uses the surveyor&apos;s own measurements, never this drawing. You can also upload the site plan on the next page.</p>
        <div className="row">
          <Button type="button" variant="ghost" size="sm" disabled={!f.ghana_post_gps.trim()} busy={a.busy === 'gps'} onClick={findGps}>Start from the GPS address</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => navigator.geolocation?.getCurrentPosition((p) => setCentre({ lng: p.coords.longitude, lat: p.coords.latitude }), () => setGpsMsg('Your phone did not share its location.'))}>Start from where I am</Button>
        </div>
        {gpsMsg ? <small className="muted">{gpsMsg}</small> : null}
        {centre ? <PlotDrawer centre={centre} points={points} onChange={setPoints} /> : null}
      </section>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={a.busy === 'save'} block>Next: documents and seller</Button>
    </form>
  );
}

/** SCR-PTL-08: the site plan and documents, and the seller (no photo of an ID card, RUL-31). */
function DocsStep({ o, onBack, onSaved }: { o: Any; onBack: () => void; onSaved: () => void }) {
  const docs = useGet<Any[]>(`/v1/orders/${o.id}/documents`);
  const [role, setRole] = useState('site_plan');
  const [s, setS] = useState({ name: o.seller?.name || '', phone: o.seller?.phone || '', email: o.seller?.email || '' });
  const [idNo, setIdNo] = useState(o.details?.seller_id_number || '');
  const a = useAction();
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); a.run('save', () => a.post(`/v1/orders/${o.id}`, { seller: s, details: { ...(o.details || {}), seller_id_number: idNo || undefined } }, 'PATCH'), undefined, onSaved); }}>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Documents</h3>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>The site plan is needed. Add the indenture or any other papers the seller gave you. Each file is stored with its fingerprint so nobody can change it later.</p>
        {(docs.data ?? []).map((d: Any) => <div key={d.id} className="spread"><span style={{ overflowWrap: 'anywhere' }}>{d.original_name || d.name || words(d.role)}</span><Proof>{words(d.role || 'stored')}</Proof></div>)}
        <div className="row">
          <Select value={role} onChange={(e) => setRole(e.target.value)} aria-label="What the file is" style={{ maxWidth: 220 }}>
            <option value="site_plan">Site plan</option><option value="indenture">Indenture</option><option value="building_permit">Building permit</option><option value="document">Other document</option>
          </Select>
          <FilePick label="Upload a file" busy={a.busy === 'doc'} onFile={(f) => { const fd = new FormData(); fd.append('file', f); fd.append('role', role); a.run('doc', () => postForm(`/v1/orders/${o.id}/documents`, fd), 'File stored', () => docs.mutate()); }} />
        </div>
      </section>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>The seller</h3>
        <Field label="Seller's name"><Input value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} /></Field>
        <Field label="Seller's phone"><Input type="tel" value={s.phone} onChange={(e) => setS({ ...s, phone: e.target.value })} /></Field>
        <Field label="Seller's email (optional)"><Input type="email" value={s.email} onChange={(e) => setS({ ...s, email: e.target.value })} /></Field>
        <Field label="Seller's national ID number, if you know it" hint="We check it with the national identity system. Do not send a photo of the card."><Input value={idNo} onChange={(e) => setIdNo(e.target.value)} /></Field>
      </section>
      <ProblemBox error={a.error} />
      <div className="row"><Button type="button" variant="ghost" onClick={onBack}>Back</Button><Button variant="primary" type="submit" busy={a.busy === 'save'} style={{ flex: 1 }}>Next: check and agree</Button></div>
    </form>
  );
}

/** W-05 · SCR-PTL-09: summary, scope statement, terms, how you heard, referral code. */
function AgreeStep({ o, onBack, onDone }: { o: Any; onBack: () => void; onDone: () => void }) {
  const terms = useGet<Any>('/v1/catalogue/terms', { country: o.country });
  const leads = useGet<Any>('/v1/catalogue/lead-sources', { country: o.country });
  const [lead, setLead] = useState(o.lead_source || '');
  const [detail, setDetail] = useState(o.lead_source_detail || '');
  const [code, setCode] = useState('');
  const [agree, setAgree] = useState(false);
  const a = useAction();
  useEffect(() => { setLead(o.lead_source || ''); }, [o.lead_source]);
  async function submit() {
    await a.run('submit', async () => {
      if (lead !== o.lead_source || detail !== o.lead_source_detail) await a.post(`/v1/orders/${o.id}`, { lead_source: lead, lead_source_detail: detail }, 'PATCH');
      return a.post(`/v1/orders/${o.id}/submit`, { accept_terms: true, terms_version: terms.data?.terms_version, scope_version: terms.data?.scope_version });
    }, undefined, onDone);
  }
  return (
    <div className="stack">
      <section className="card">
        <KV items={[
          ['Check', `${o.product_name}${o.tier_name ? ` · ${o.tier_name}` : ''}`],
          ['Place', [o.asset?.locality, o.asset?.plot_number && `plot ${o.asset.plot_number}`, o.asset?.ghana_post_gps].filter(Boolean).join(', ') || '—'],
          ['Seller', o.seller?.name || '—'],
          ['Price', <span key="p"><Money value={o.price} />{o.local_price ? <> · <Money value={o.local_price} /></> : null}</span>],
          ...(Number(o.discount?.amount) > 0 ? [['Referral discount', <Money key="d" value={o.discount} />] as [string, React.ReactNode]] : []),
          ['Guide', o.guides?.guide_for_you ? <span key="g"><Money value={o.guides.guide_for_you} /> · {o.guides.note}</span> : '—'],
        ]} />
      </section>
      {o.missing?.length ? (
        <div className="card stack" role="status"><strong>Still needed</strong><ul style={{ margin: 0, paddingLeft: 18 }}>{o.missing.map((m: Any) => <li key={m.pointer}><span className="mono">{m.pointer.replace(/^\//, '')}</span>: {m.message}</li>)}</ul></div>
      ) : null}
      {terms.data ? <>
        <section className="card stack"><h3 style={{ margin: 0 }}>{terms.data.scope.title}</h3><p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{terms.data.scope.text}</p><small className="mono muted">{terms.data.scope_version}</small></section>
        <section className="card stack"><h3 style={{ margin: 0 }}>{terms.data.terms.title}</h3><p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{terms.data.terms.text}</p><small className="mono muted">{terms.data.terms_version}</small></section>
      </> : <Skeleton />}
      <Field label="How did you hear about Tenmina?">
        <Select value={lead} onChange={(e) => setLead(e.target.value)} required>
          <option value="">Choose one</option>
          {(leads.data?.lead_sources ?? []).map((l: string) => <option key={l} value={l}>{LEAD_LABELS[l] ?? words(l)}</option>)}
        </Select>
      </Field>
      {lead === 'other' || lead === 'association' ? <Field label="Which one? (optional)"><Input value={detail} onChange={(e) => setDetail(e.target.value)} /></Field> : null}
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div style={{ flex: 1, minWidth: 180 }}><Field label="Referral code (optional)"><Input value={code || o.referral_code || ''} onChange={(e) => setCode(e.target.value.toUpperCase())} /></Field></div>
        {o.referral_code ? <Button variant="ghost" busy={a.busy === 'ref'} onClick={() => a.run('ref', () => a.post(`/v1/orders/${o.id}/referral`, undefined, 'DELETE'), 'Code removed', onDone)}>Remove</Button>
          : <Button variant="ghost" disabled={!code} busy={a.busy === 'ref'} onClick={() => a.run('ref', () => a.post(`/v1/orders/${o.id}/referral`, { code }), 'Code applied', onDone)}>Apply</Button>}
      </div>
      <label className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap', gap: 10 }}>
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} style={{ width: 24, height: 24, flex: 'none', accentColor: '#0b0b0b' }} />
        <span>I have read what the report covers and the terms, and I agree to them.</span>
      </label>
      <ProblemBox error={a.error} />
      <div className="row"><Button variant="ghost" onClick={onBack}>Back</Button><Button variant="primary" style={{ flex: 1 }} disabled={!agree || !lead || !terms.data} busy={a.busy === 'submit'} onClick={submit}>Agree and go to payment</Button></div>
    </div>
  );
}

/** W-06 · SCR-PTL-10: Tenmina's fee only, by card or mobile money. */
function PayStep({ o, refresh }: { o: Any; refresh: () => void }) {
  const [method, setMethod] = useState('card');
  const [wallet, setWallet] = useState('');
  const pays = useGet<Any>(`/v1/orders/${o.id}/payments`);
  const a = useAction();
  const router = useRouter();
  const payments = Array.isArray(pays.data) ? pays.data : pays.data?.items ?? [];
  if (o.status === 'paid' || o.status === 'refunded') {
    return (
      <div className="stack">
        <div className="card stack">
          <Proof>Paid <When value={o.paid_at} /></Proof>
          <p style={{ margin: 0 }}>We have opened your case. You will see each step in the case tracker.</p>
          {o.case_id ? <Link className="btn btn-primary" href={`/property/cases/${o.case_id}`}>Open the case</Link> : null}
        </div>
        {payments.map((p: Any) => <Link key={p.id} href={`/property/payments/${p.id}`} className="card card-link"><div className="spread"><span>{words(p.method)} · {words(p.status)}</span><Money value={p.amount} /></div></Link>)}
      </div>
    );
  }
  if (o.status === 'cancelled') return <p className="muted">This order was cancelled{o.cancel_reason ? `: ${o.cancel_reason}` : '.'}</p>;
  return (
    <Ink>
      <div className="stack" style={{ gap: 4 }}>
        <div className="label">Tenmina&apos;s fee for {o.product_name}{o.tier_name ? `, ${o.tier_name}` : ''}</div>
        <div style={{ fontSize: 36, fontWeight: 800 }}><Money value={o.price} /></div>
        {o.local_price ? <div className="muted"><Money value={o.local_price} /> · {o.guides?.note}</div> : null}
      </div>
      <p className="muted" style={{ margin: 0 }}>This pays for the work only. Land money never goes to Tenmina: it goes to a licensed bank as escrow agent.</p>
      {o.last_payment_message ? <div className="card">{o.last_payment_message}</div> : null}
      <RadioCard name="method" checked={method === 'card'} onChange={() => setMethod('card')}><strong>Card</strong></RadioCard>
      <RadioCard name="method" checked={method === 'mobile_money'} onChange={() => setMethod('mobile_money')}><strong>Mobile money</strong></RadioCard>
      {method === 'mobile_money' ? <Field label="Wallet phone number"><Input type="tel" value={wallet} onChange={(e) => setWallet(e.target.value)} /></Field> : null}
      <ProblemBox error={a.error} />
      <Button variant="primary" block disabled={!o.can_pay} busy={a.busy === 'pay'} onClick={() => a.run('pay', () => a.post<Any>(`/v1/orders/${o.id}/payments`, { method, wallet_phone: method === 'mobile_money' ? wallet : undefined, return_url: `${location.origin}/property/orders/${o.id}` }), undefined, (r) => router.push(`/property/payments/${r.payment.id}`))}>
        Pay <Money value={o.price} />
      </Button>
      {!o.can_pay && !o.terms?.current ? <p className="muted">The terms changed since you agreed. <Button variant="ghost" size="sm" onClick={() => a.run('edit', () => a.post(`/v1/orders/${o.id}/edit`), undefined, refresh)}>Read and agree again</Button></p> : null}
      <div className="row">
        <Button variant="ghost" size="sm" busy={a.busy === 'edit'} onClick={() => a.run('edit', () => a.post(`/v1/orders/${o.id}/edit`), 'You can change the order now', refresh)}>Change the order</Button>
        <Button variant="ghost" size="sm" busy={a.busy === 'cancel'} onClick={() => a.run('cancel', () => a.post(`/v1/orders/${o.id}/cancel`, { reason: 'Cancelled by the client before payment' }), 'Order cancelled', refresh)}>Cancel the order</Button>
      </div>
      {a.toast}
    </Ink>
  );
}

export default function OrderPage() {
  return <Suspense><Wizard /></Suspense>;
}
