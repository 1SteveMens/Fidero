'use client';
import { formatMoney } from '@tenmina/api-client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Button, Chip, Money, NeedsYou, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { AcctCard, AcctRow, PageHead, Proof, Section, list, money, useAction, words, type Any } from '@/components/kit';
import { ApprovalChain, ESCROW_SENTENCE, FreezeBanner, PayeeChanges, RELEASE_SENTENCE } from '@/components/escrow-bits';

/** W-09 · SCR-PTL-17: the escrow tracker. Money is held by the bank, never by Tenmina. */
export default function EscrowTracker() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const q = useGet<Any>(`/v1/escrows/${id}`);
  const ins = useGet<Any[]>(`/v1/escrows/${id}/release-instructions`);
  const conv = useGet<Any[]>(`/v1/escrows/${id}/conversions`);
  const stmt = useGet<Any>(`/v1/escrows/${id}/statement`);
  const terms = useGet<Any>(q.data?.status === 'proposed' ? '/v1/legal-texts/escrow_terms/current' : null, { country: q.data?.country });
  const a = useAction();
  if (q.isLoading) return <Skeleton lines={8} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const e = q.data;
  const pi = e.payment_instructions ?? {};
  const me_party = (e.parties ?? []).find((p: Any) => p.person === me?.id && p.role === 'buyer');
  const instructions = list(ins.data);
  const awaiting = instructions.filter((i: Any) => i.status === 'awaiting_client');
  const closed = (e.conditions ?? []).filter((c: Any) => c.status === 'closed').length;
  const refunds = instructions.filter((i: Any) => i.kind === 'refund');
  const canPayIn = ['agreed', 'funded', 'partly_released', 'ready_to_release'].includes(e.status) || e.kind === 'held_funds';
  return (
    <div className="stack" style={{ gap: 20 }}>
      <PageHead back={{ href: e.kind === 'held_funds' ? '/family' : '/property', label: e.kind === 'held_funds' ? 'Family' : 'Property' }} label={`Escrow ${e.reference} · held by ${pi.bank_name ?? 'the partner bank'}`} title={e.title} />
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

      <Section title="Money at the bank">
        <AcctRow>
          {(e.funds ?? []).map((f: Any) => (
            <AcctCard key={f.currency} title={pi.account_name || 'Escrow account'} reference={f.virtual_account_ref || pi.virtual_account_ref} amount={money(f.held_at_bank, f.currency)} holder={me?.full_name ?? ''} bank={pi.bank_name}
              note={Number(f.instructed_awaiting_bank) > 0 ? `${formatMoney({ amount: String(f.instructed_awaiting_bank), currency: f.currency })} instructed, waiting for the bank` : f.last_bank_event_at ? `Bank confirmed ${new Date(String(f.last_bank_event_at).replace(' ', 'T')).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}` : 'Nothing received yet'} />
          ))}
        </AcctRow>
        <p className="muted" style={{ margin: 0 }}>Your money is held by {pi.bank_name ?? 'the partner bank'}, not by Tenmina. {Number(e.agreed_price?.amount) > 0 ? <>Price: <Money value={e.agreed_price} />.</> : null} {e.conversion_choice === 'at_release' ? 'Held in your currency until release (your choice).' : 'Converted when it arrives.'}</p>
        {Number(e.held_back_amount) > 0 ? <div className="card"><strong>Release 2 of 2.</strong> Held back until: {e.held_back_condition}. <Money value={money(e.held_back_amount, e.currency)} /></div> : null}
        {canPayIn ? (
          <div className="row">
            <Link className="btn btn-primary" href={`/property/escrows/${id}/pay-in`}>{e.kind === 'held_funds' ? 'Add money' : 'Choose how to pay in'}</Link>
            <Link className="btn btn-ghost" href={`/property/escrows/${id}/bank-details`}>Bank details</Link>
          </div>
        ) : null}
      </Section>

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

      <Section title="Payments from this escrow">
        {instructions.filter((i: Any) => i.kind !== 'refund').length ? instructions.filter((i: Any) => i.kind !== 'refund').map((i: Any) => (
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
          {!refunds.length ? <p className="muted">Any money at the bank goes back only to the account it came from. Tenmina prepares the refund and two staff approve it.</p> : null}
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
