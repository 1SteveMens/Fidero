'use client';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { Button, Chip, CodeBoxes, Dialog, Field, Input, Money, ProblemBox, Select, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, RadioCard, useAction, words, type Any } from '@/components/kit';

const ROUTE_LABEL: Record<string, string> = {
  escrow_fx_account: "Bank transfer in your currency to this escrow's own account at the partner bank",
  escrow_local_account: 'Send from your own bank into the escrow account; your bank converts',
  transfer_partner: "A transfer service into this escrow's local account",
  local_bank: 'From a bank in the country, no exchange',
};
const CURRENCIES = ['GBP', 'USD', 'EUR', 'CAD'];

/** W-44 · SCR-PTL-56: choose how to pay in. Every fee and the margin shown before anything is sent (RUL-35). */
export default function PayIn() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const router = useRouter();
  const e = useGet<Any>(`/v1/escrows/${id}`);
  const guides = useGet<Any[]>(e.data ? '/v1/fx-guides' : null, { country: e.data?.country });
  const local = e.data?.currency;
  const [cur, setCur] = useState('');
  const [amount, setAmount] = useState('');
  useEffect(() => {
    if (!e.data || cur) return;
    const res = me?.residence_country === 'US' ? 'USD' : me?.residence_country === 'GB' ? 'GBP' : me?.residence_country === 'CA' ? 'CAD' : 'EUR';
    setCur(res);
    const g = (guides.data ?? []).find((x: Any) => x.base_currency === res);
    const left = Number(e.data.agreed_price?.amount || 0) - Number(e.data.funds?.[0]?.held_at_bank || 0);
    if (g && left > 0) setAmount((left / Number(g.rate)).toFixed(2));
  }, [e.data, guides.data, me, cur]);
  const params = useMemo(() => (cur && Number(amount) > 0 ? { currency: cur, amount } : null), [cur, amount]);
  const routes = useGet<Any>(params ? `/v1/escrows/${id}/deposit-routes` : null, params ?? undefined);
  const [pick, setPick] = useState<number>(0);
  const [choice, setChoice] = useState<string>('');
  const [compare, setCompare] = useState(false);
  const [quote, setQuote] = useState<Any>(null);
  const [code, setCode] = useState('');
  const a = useAction();
  if (e.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!e.data) return <Ink><ProblemBox error={e.error} /></Ink>;
  const esc = e.data;
  const rs: Any[] = routes.data?.routes ?? [];
  const r = rs[pick];
  const foreign = cur && cur !== local;
  const conv = choice || esc.conversion_choice || 'on_deposit';
  const notAgreed = esc.status === 'proposed';
  async function continueRoute() {
    if (!r) return;
    const q = await a.run('quote', () => a.post<Any>(`/v1/escrows/${id}/fx-quotes`, { purpose: 'deposit', route: r.route, amount: { amount, currency: cur }, provider_partner_id: r.provider_partner_id }));
    if (q) { setQuote(q); setCode(''); }
  }
  async function accept() {
    await a.run('accept', async () => {
      if (foreign && conv !== esc.conversion_choice && esc.kind !== 'held_funds') await a.post(`/v1/escrows/${id}/conversion-choice`, { conversion_choice: conv, code }, 'PUT');
      return a.post(`/v1/fx-quotes/${quote.id}/accept`, { shown_sha256: quote.shown_sha256, code });
    }, undefined, () => router.push(`/property/escrows/${id}/bank-details?quote=${quote.id}`));
  }
  return (
    <Ink>
      <PageHead back={{ href: `/property/escrows/${id}`, label: `Escrow ${esc.reference}` }} label="Choose how to pay in" title="How do you want to pay in?" />
      {Number(esc.agreed_price?.amount) > 0 ? <div className="spread"><span className="label">Price</span><strong style={{ fontSize: 22 }}><Money value={esc.agreed_price} /></strong></div> : null}
      <p className="muted" style={{ margin: 0 }}>The payee is paid in {local}. Refunds go back only to the account the money came from, including through a transfer service.</p>
      {notAgreed ? <div className="card">The bank opens the escrow once everyone has accepted the terms. You can see the routes now, but you cannot pay yet.</div> : null}
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div style={{ width: 120 }}><Field label="You send"><Select value={cur} onChange={(ev) => setCur(ev.target.value)}>{[...CURRENCIES, local].filter(Boolean).map((c) => <option key={c} value={c}>{c}</option>)}</Select></Field></div>
        <div style={{ flex: 1, minWidth: 140 }}><Field label="Amount"><Input inputMode="decimal" value={amount} onChange={(ev) => setAmount(ev.target.value.replace(/[^\d.]/g, ''))} /></Field></div>
      </div>
      {routes.data ? (
        <>
          <div className="card stack" style={{ gap: 4 }}>
            <strong>{routes.data.tenmina_margin_line}</strong>
            <span className="muted" style={{ fontSize: 14 }}>The bank or transfer service may take a margin. We show it on each route.</span>
            {rs[0] ? <div className="mono" style={{ fontSize: 13 }}>Reference rate {Number(rs[0].reference_rate).toFixed(4)} {rs[0].to_currency} per {rs[0].from_currency} · {rs[0].reference_source} · <When value={rs[0].reference_published_at} withTime /></div> : null}
          </div>
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="sr-only">Routes</legend>
            {rs.map((x, i) => (
              <RadioCard key={`${x.route}-${x.provider_partner_id}`} name="route" checked={pick === i} onChange={() => setPick(i)}>
                <strong>{ROUTE_LABEL[x.route] ?? words(x.route)}</strong>
                <div className="muted" style={{ fontSize: 14 }}>{x.provider}</div>
                <div className="mono" style={{ fontSize: 13, marginTop: 4 }}>Rate {Number(x.offered_rate).toFixed(4)} · margin {Number(x.margin_pct).toFixed(2)}%</div>
                {x.fees?.length ? x.fees.map((f: Any) => <div key={f.name} style={{ fontSize: 14 }}>{f.name}: {f.charged_by} {f.currency} {f.amount}</div>) : <div style={{ fontSize: 14 }}>No fee</div>}
                <div style={{ fontSize: 14 }}>{x.limits_text || 'Limit: none stated'}{x.transfers_needed > 1 ? `, so ${x.transfers_needed} transfers` : ''}{x.over_limit ? ' · over this route\'s limit' : ''}</div>
                <div style={{ marginTop: 4 }}>You send <Money value={{ amount: x.from_amount, currency: x.from_currency }} />, which gives <strong><Money value={{ amount: x.expected_to_amount, currency: x.to_currency }} /></strong>{x.is_estimate ? ' (an estimate)' : ''}</div>
                <div className="muted" style={{ fontSize: 13 }}>{Number(x.partner_payment_to_tenmina) > 0 ? `Tenmina receives ${x.from_currency} ${x.partner_payment_to_tenmina} from ${x.provider}.` : `Tenmina receives nothing from ${x.provider}.`} {x.note}</div>
              </RadioCard>
            ))}
            {(routes.data.unavailable ?? []).map((u: Any, i: number) => <p key={i} className="muted" style={{ margin: 0 }}>{u.provider ?? words(u.route)}: {u.reason ?? 'not available now'}.</p>)}
          </fieldset>
          {foreign && esc.kind !== 'held_funds' ? (
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="label" style={{ marginBottom: 8 }}>When should your {cur} change into {local}?</legend>
              <RadioCard name="conv" checked={conv === 'on_deposit'} onChange={() => setChoice('on_deposit')}><strong>When it arrives</strong><div className="muted" style={{ fontSize: 14 }}>The {local} amount is fixed from then on.</div></RadioCard>
              <RadioCard name="conv" checked={conv === 'at_release'} onChange={() => setChoice('at_release')}><strong>Hold {cur} until release</strong><div className="muted" style={{ fontSize: 14 }}>Send {esc.fx_buffer_pct ? `${esc.fx_buffer_pct}%` : 'a little'} extra as a buffer. If the {local} amount falls short, you top up first. Unused money comes back to you.</div></RadioCard>
            </fieldset>
          ) : null}
          {routes.data.comparison ? <Button variant="ghost" onClick={() => setCompare(true)}>{routes.data.comparison.status === 'complete' ? "Compare today's rates" : "Today's comparison (incomplete)"}</Button> : null}
        </>
      ) : routes.isLoading ? <Skeleton /> : <ProblemBox error={routes.error} />}
      <ProblemBox error={a.error} />
      <Button variant="primary" block disabled={!r || notAgreed || r.over_limit} busy={a.busy === 'quote'} onClick={continueRoute}>Continue with this route</Button>

      <Dialog open={!!quote} onClose={() => setQuote(null)} title="Your quote" ink>
        {quote ? (
          <div className="stack">
            <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{quote.shown_text}</p>
            <div className="mono muted" style={{ fontSize: 13 }}>Good until <When value={quote.expires_at} withTime /></div>
            {me?.mfa_enabled ? <><p className="muted" style={{ margin: 0 }}>Enter the code from your authenticator app to record this quote.</p><CodeBoxes value={code} onChange={setCode} autoFocus /></> : <p>Set up your authenticator app in Account first.</p>}
            <ProblemBox error={a.error} />
            <Button variant="action" block disabled={code.length !== 6} busy={a.busy === 'accept'} onClick={accept}>Accept and see the bank details</Button>
          </div>
        ) : null}
      </Dialog>
      <Dialog open={compare} onClose={() => setCompare(false)} title={`Today's rates · ${routes.data?.comparison?.pair ?? ''}`} ink>
        {routes.data?.comparison ? (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>{routes.data.comparison.statement}</p>
            <p className="muted" style={{ margin: 0 }}>What the payee gets for {cur} {routes.data.comparison.send_amount}, after all fees, highest first.</p>
            {(routes.data.comparison.items ?? []).map((it: Any) => (
              <div key={it.provider} className="card">
                <div className="spread"><strong>{it.provider}</strong><span>{local} {it.delivered_amount}</span></div>
                <div className="mono muted" style={{ fontSize: 13 }}>{Number(it.rate).toFixed(4)} · margin {Number(it.margin_pct).toFixed(2)}% · fee {it.fees_total} · {words(it.kind)}{it.stale ? ' · not updated today' : ''}</div>
                {routes.data.comparison.bank_best_rate && it.rank === 1 ? <Chip tone="lime">Best rate today</Chip> : null}
              </div>
            ))}
          </div>
        ) : null}
      </Dialog>
    </Ink>
  );
}
