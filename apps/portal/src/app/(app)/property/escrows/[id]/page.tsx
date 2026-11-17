'use client';
import { formatMoney } from '@tenmina/api-client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button, Chip, Money, NeedsYou, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { PageHead, Proof, Seal, Section, list, money, useAction, words, type Any } from '@/components/kit';
import { ApprovalChain, ESCROW_SENTENCE, FreezeBanner, PayeeChanges, RELEASE_SENTENCE } from '@/components/escrow-bits';
import { KeepInAccount, SetAside, commitmentState, kindWord, type Commitment } from '@/components/account-card';

const TRANSFER = ['commitment_fund', 'commitment_return'];

/** W-09 · SCR-PTL-17: a commitment inside the client's Tenmina account (decision 2026-11-17), with its terms,
 * conditions and releases. Money is held by the bank, never by Tenmina. Also served at /money/commitments/{id}. */
export default function EscrowTracker() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const router = useRouter();
  const q = useGet<Any>(`/v1/escrows/${id}`);
  const isClient = !!q.data && q.data.client === me?.id;
  const detail = useGet<Any>(isClient && q.data.kind !== 'held_funds' ? `/v1/account/commitments/${id}` : null);
  const acct = useGet<Any>(isClient ? '/v1/account' : null, { country: q.data?.country });
  const [setting, setSetting] = useState(false);
  useEffect(() => { if (q.data?.kind === 'held_funds') router.replace('/money'); }, [q.data?.kind, router]);
  const ins = useGet<Any[]>(`/v1/escrows/${id}/release-instructions`);
  const conv = useGet<Any[]>(`/v1/escrows/${id}/conversions`);
  const stmt = useGet<Any>(`/v1/escrows/${id}/statement`);
  const terms = useGet<Any>(q.data?.status === 'proposed' ? '/v1/legal-texts/escrow_terms/current' : null, { country: q.data?.country });
  const a = useAction();
  if (q.isLoading || q.data?.kind === 'held_funds') return <Skeleton lines={8} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const e = q.data;
  const pi = e.payment_instructions ?? {};
  const me_party = (e.parties ?? []).find((p: Any) => p.person === me?.id && p.role === 'buyer');
  const instructions = list(ins.data);
  const awaiting = instructions.filter((i: Any) => i.status === 'awaiting_client');
  const closed = (e.conditions ?? []).filter((c: Any) => c.status === 'closed').length;
  const refunds = instructions.filter((i: Any) => i.kind === 'cancel_refund');
  const payments = instructions.filter((i: Any) => i.kind !== 'cancel_refund' && !TRANSFER.includes(i.kind));
  const c: Commitment | undefined = detail.data?.commitment;
  const transfers: Any[] = detail.data?.transfers ?? [];
  const freeBal = (acct.data?.balances ?? []).find((b: Any) => b.currency === e.currency)?.free_balance;
  const bank = (pi.bank_name ?? 'the partner bank').replace(/\s*\[TO VERIFY\]/, '');
  const refresh = () => { q.mutate(); detail.mutate(); acct.mutate(); ins.mutate(); stmt.mutate(); setSetting(false); };
  return (
    <div className="stack" style={{ gap: 20 }}>
      <PageHead back={isClient ? { href: '/money', label: 'Your Tenmina account' } : { href: '/property', label: 'Property' }} label={`${kindWord(e.kind)} · commitment ${e.reference}`} title={e.title} />
      <div className="card-ink stack" style={{ gap: 6 }}>
        <span className="label" style={{ color: '#a9a69e' }}>Now</span>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{ESCROW_SENTENCE[e.status] ?? words(e.status)}</div>
      </div>
      <FreezeBanner e={e} />
      {awaiting.map((i: Any) => <NeedsYou key={i.id} title={`Approve ${i.subject_label || 'the release'}`} detail={`${formatMoney(i.money)} to ${i.payee_name}. Nothing is paid until you approve.`} href={`/property/releases/${i.id}`} />)}
      <PayeeChanges escrowId={e.id} />

      {e.status === 'proposed' ? (
        <Section title="Accept the escrow terms">
          {(e.parties ?? []).filter((p: Any) => p.must_accept).map((p: Any) => (
            <div key={p.id} className="spread card"><span>{p.name} · {words(p.role)}</span>{p.accepted_current_terms ? <Proof>Accepted</Proof> : <Chip>Waiting</Chip>}</div>
          ))}
          {(e.agreement_blockers ?? []).length ? <div className="card"><strong>Before the bank can open the escrow</strong><ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{e.agreement_blockers.map((b: Any, i: number) => <li key={i}>{b.message ?? String(b)}</li>)}</ul></div> : null}
          {terms.data ? <div className="card"><strong>{terms.data.title}</strong> <span className="mono muted">v{terms.data.version}</span><p style={{ whiteSpace: 'pre-wrap', margin: '6px 0 0' }}>{terms.data.text}</p></div> : null}
          {me_party && !me_party.accepted_current_terms ? (
            <Button variant="action" busy={a.busy === 'acc'} onClick={() => a.run('acc', () => a.post(`/v1/escrows/${id}/acceptances`, { party_id: me_party.id }), 'You accepted the terms', () => q.mutate())}>I accept the escrow terms</Button>
          ) : null}
        </Section>
      ) : null}

      <Section title="Inside your Tenmina account">
        <div className="acct-one">
          <div className="acct-head">
            <div style={{ minWidth: 0 }}>
              <div className="acct-label">Set aside for this {kindWord(e.kind).toLowerCase()}</div>
              <div className="mono" style={{ fontSize: 13 }}>{detail.data?.account?.reference ?? pi.account_reference ?? e.reference}</div>
            </div>
            <Seal />
          </div>
          <div className="acct-total">{c ? <Money value={c.set_aside} /> : (e.funds ?? []).map((f: Any) => <div key={f.currency}><Money value={money(f.held_at_bank, f.currency)} /></div>)}</div>
          {c ? (
            <>
              <div className="acct-split">
                <div><div className="acct-label">Agreed</div><div className="acct-fig"><Money value={c.agreed} /></div></div>
                <div><div className="acct-label">Paid out</div><div className="acct-fig"><Money value={c.paid_out} /></div></div>
                <div><div className="acct-label">Still to set aside</div><div className="acct-fig"><Money value={c.still_to_set_aside} /></div></div>
                <div><div className="acct-label">On its way in</div><div className="acct-fig"><Money value={c.on_its_way_in} /></div></div>
              </div>
              <div className="acct-commit-state" style={{ marginTop: 10 }}>{commitmentState(c)}</div>
            </>
          ) : null}
          <div className="acct-foot"><span>{(me?.full_name ?? '').toUpperCase()}</span><span style={{ color: '#a9a69e' }}>{bank}</span></div>
        </div>
        <p className="muted" style={{ margin: 0 }}>{bank} holds this money for this deal only, not Tenmina. It pays only {c?.payees?.length ? c.payees.join(', ') : 'the verified payee'}, on proof, after you approve. {Number(e.agreed_price?.amount) > 0 ? <>Price: <Money value={e.agreed_price} />.</> : null}</p>
        {Number(e.held_back_amount) > 0 ? <div className="card"><strong>Release 2 of 2.</strong> Held back until: {e.held_back_condition}. <Money value={money(e.held_back_amount, e.currency)} /></div> : null}
        {c?.can_fund && !setting ? (
          <div className="row">
            <Button variant="primary" onClick={() => setSetting(true)}>Set aside from my balance</Button>
            <Link className="btn btn-ghost" href="/money/pay-in">How to pay in</Link>
          </div>
        ) : null}
        {c && setting ? <div className="card stack"><SetAside c={c} free={freeBal} onDone={refresh} /><Button variant="ghost" onClick={() => setSetting(false)}>Not now</Button></div> : null}
        {c?.can_keep_in_account ? <KeepInAccount c={c} onDone={refresh} /> : null}
      </Section>

      {transfers.length ? (
        <Section title="Money set aside">
          {transfers.map((t: Any) => (
            <div key={t.id} className="card spread">
              <span><strong>{t.kind === 'commitment_fund' ? 'From your free balance' : 'Back to your free balance'}</strong><br /><span className="muted" style={{ fontSize: 14 }}>{t.status === 'confirmed' ? 'The bank confirmed it.' : t.status === 'sent' ? 'Waiting for the bank to confirm it.' : words(t.status)}</span></span>
              <span style={{ textAlign: 'right' }}><Money value={t.money} />{t.status === 'confirmed' ? <><br /><Proof>Bank confirmed</Proof></> : null}</span>
            </div>
          ))}
        </Section>
      ) : null}

      {e.conditions?.length ? (
        <Section title={`Conditions (${closed} of ${e.conditions.length} closed)`}>
          <div className="card" style={{ paddingTop: 6, paddingBottom: 6 }}>
            {e.conditions.map((c: Any) => (
              <div key={c.id} className="check-row">
                <span className={`tick ${c.status === 'closed' ? 'done' : ''}`} aria-hidden>{c.status === 'closed' ? '✓' : ''}</span>
                <div><div style={{ fontWeight: 600 }}>{c.text}</div>{c.status === 'closed' ? <div className="muted" style={{ fontSize: 13 }}>{c.closed_note}</div> : c.reopen_reason ? <div className="muted" style={{ fontSize: 13 }}>Reopened: {c.reopen_reason}</div> : null}{c.release_part !== 'main' ? <div className="label">Held-back share</div> : null}</div>
                <span className="mono" style={{ fontSize: 12 }}>{c.status === 'closed' ? <>closed <When value={c.closed_at} /></> : 'open'}</span>
              </div>
            ))}
            {e.kind === 'purchase' ? (
              <div className="check-row">
                <span className={`tick ${e.fresh_search_result_date ? 'done' : ''}`} aria-hidden>{e.fresh_search_result_date ? '✓' : ''}</span>
                <div><div style={{ fontWeight: 600 }}>Fresh search and site check</div><div className="muted" style={{ fontSize: 13 }}>Must be in date when you approve and when Tenmina sends the instruction.</div></div>
                <span className="mono" style={{ fontSize: 12 }}>{e.fresh_search_result_date ? <When value={e.fresh_search_result_date} /> : 'not yet'}</span>
              </div>
            ) : null}
          </div>
        </Section>
      ) : null}

      <Section title="Payments from this commitment">
        {payments.length ? payments.map((i: Any) => (
          <Link key={i.id} href={`/property/releases/${i.id}`} className="card card-link stack" style={{ gap: 6 }}>
            <div className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              <div><div className="label">{words(i.kind)} · {words(i.release_part)}</div><strong>{i.subject_label || i.payee_name}</strong><div className="muted" style={{ fontSize: 14 }}>{RELEASE_SENTENCE[i.status] ?? words(i.status)}</div></div>
              <Money value={i.money} />
            </div>
            <ApprovalChain ins={i} />
          </Link>
        )) : <p className="muted">No payment is waiting. When every condition is closed, Tenmina prepares the release and asks you first. You approve before any Tenmina staff.</p>}
        <p className="muted" style={{ fontSize: 14, margin: 0 }}>No waiting period after the last approval. The bank pays the verified payee only.</p>
      </Section>

      {refunds.length || e.status === 'cancelled' ? (
        <Section title="Refunds">
          {refunds.map((r: Any) => <div key={r.id} className="card"><Money value={r.money} /> back to the account it came from{r.payee_account_last4 ? `, ending ${r.payee_account_last4}` : ''}. {RELEASE_SENTENCE[r.status] ?? words(r.status)}</div>)}
          {!refunds.length ? <p className="muted">Money set aside goes back only to the account it came from, unless you choose to keep it in your Tenmina account. Tenmina prepares the refund and two staff approve it.</p> : null}
        </Section>
      ) : null}

      {list(conv.data).length ? (
        <Section title="Currency conversions">
          {list(conv.data).map((c: Any) => <div key={c.id} className="card"><div className="spread"><span>{c.quote?.from_currency} {c.from_amount} → {c.quote?.to_currency} {c.to_amount}</span><Chip>{words(c.status)}</Chip></div><div className="mono muted" style={{ fontSize: 13 }}>Rate {c.applied_rate} · margin {c.margin_pct}% · reference {c.reference_rate}</div>{c.short_of_quote ? <div>The bank gave less than the quote. Tenmina is claiming the difference.</div> : null}</div>)}
        </Section>
      ) : null}

      {list(stmt.data?.lines).length ? (
        <Section title="Statement">
          {list(stmt.data.lines).map((l: Any, i: number) => <div key={i} className="spread card"><span><When value={l.date || l.occurred_at} /> · {l.description || words(l.kind)}</span><Money value={money(l.amount, l.currency)} /></div>)}
        </Section>
      ) : null}

      <ProblemBox error={a.error} />
      <div className="row">
        {e.report_id ? <Link className="btn btn-ghost" href={`/property/reports/${e.report_id}`}>The report</Link> : null}
        {e.case_id ? <Link className="btn btn-ghost" href={`/property/cases/${e.case_id}`}>The case</Link> : null}
        {e.status !== 'cancelled' && e.status !== 'released' ? <Link className="btn btn-ghost" href={`/property/disputes/new?escrow=${id}`}>Open a dispute</Link> : null}
      </div>
      {a.toast}
    </div>
  );
}
