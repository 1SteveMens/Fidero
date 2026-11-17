'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Button, Dialog, HoldButton, Money, ProblemBox, Skeleton, Ticket, useGet } from '@tenmina/web-ui';
import { ApiError } from '@tenmina/api-client';
import { Seal, money, useAction, useCountry, type Any } from './kit';
import { FactorField, useWebFactor } from './secondfactor';

/** Press and hold, then the client's second factor (RUL-11, FR-ACC-015): a 6-digit code sent by SMS ("Send code",
 * then the boxes), or the authenticator's code for a client who set one up. The code steps up first; the move then
 * rests on that fresh step-up. It pays nobody, so no Tenmina staff approve it; the bank confirms it before it
 * counts. Silence is never approval: nothing moves until the client holds and enters the code. */
function HoldThenCode({ label, onApprove, disabled }: { label: string; onApprove: () => Promise<unknown>; disabled?: boolean }) {
  const f = useWebFactor();
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function go() {
    setBusy(true); setError(null);
    try { await f.stepUp(); await onApprove(); setAsk(false); f.reset(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const canCode = f.method === 'totp' || f.method === 'sms';
  return (
    <>
      <HoldButton label={label} tone="lime" disabled={disabled} onConfirm={() => { setError(null); f.reset(); setAsk(true); }} />
      {!ask ? <ProblemBox error={error} /> : null}
      <Dialog open={ask} onClose={() => setAsk(false)} title="Confirm it is you" ink>
        <div className="stack">
          <FactorField f={f} autoFocus />
          <ProblemBox error={error} />
          {canCode ? <Button variant="primary" busy={busy} disabled={!f.ready} onClick={go} block>Confirm</Button> : null}
        </div>
      </Dialog>
    </>
  );
}

/** FR-ESC-027: set money aside for a commitment from the free balance. */
export function SetAside({ c, free, onDone }: { c: Commitment; free?: Any; onDone: () => void }) {
  const a = useAction();
  const left = Number(c.still_to_set_aside.amount);
  const avail = free ? Number(free.amount) : left;
  const [amount, setAmount] = useState(String(Math.max(0, Math.min(left, avail)).toFixed(2)));
  const n = Number(amount);
  const tooMuch = n > left || n > avail;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <label className="field">
        <span>Amount to set aside ({c.currency})</span>
        <input className="input mono" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ''))} />
      </label>
      <div className="muted" style={{ fontSize: 14 }}>Still to set aside: <Money value={c.still_to_set_aside} />{free ? <>. Free balance: <Money value={free} /></> : null}.</div>
      {tooMuch ? <div className="banner-blocked" role="status">{n > left ? 'That is more than this deal still needs.' : 'Your free balance is not enough. Pay into your account first.'}</div> : null}
      <Ticket
        top={<div className="stack" style={{ gap: 4 }}><div className="label" style={{ color: '#6a675f' }}>Set aside</div><div style={{ fontSize: 30, fontWeight: 800 }}><Money value={money(n.toFixed(2), c.currency)} /></div></div>}
        bottom={<div className="stack" style={{ gap: 4 }}><div className="label" style={{ color: '#6a675f' }}>Inside your account, for</div><div style={{ fontWeight: 800, fontSize: 18 }}>{c.title}</div>
          <div style={{ fontSize: 13, color: '#6a675f' }}>Nobody is paid now. The bank keeps it for this deal only. It is released only to {c.payees.length ? c.payees.join(', ') : 'the verified payee'}, on proof, after you approve.</div></div>}
      />
      <HoldThenCode label="Hold to set aside" disabled={!(n > 0) || tooMuch} onApprove={() => a.post('/v1/account/commitments', { commitment_id: c.id, amount: { amount: n.toFixed(2), currency: c.currency }, gesture: 'press_and_hold' }).then(() => { a.show('Asked the bank. It counts once the bank confirms it.'); onDone(); })} />
      {a.toast}
    </div>
  );
}

/** FR-ESC-028: a cancelled commitment's money goes back to the account it came from, unless the client keeps it. */
export function KeepInAccount({ c, onDone }: { c: Commitment; onDone: () => void }) {
  const a = useAction();
  return (
    <div className="card stack" style={{ gap: 10 }}>
      <strong>This commitment is being cancelled</strong>
      <span>The <Money value={c.available_to_instruct} /> set aside goes back to the bank account it came from. Two Tenmina staff approve that refund.</span>
      <span className="muted">You can keep it in your Tenmina account instead, to use for something else. Only you can choose this.</span>
      <HoldThenCode label="Hold to keep it in my account" onApprove={() => a.post(`/v1/account/commitments/${c.id}/keep-in-account`, { gesture: 'press_and_hold' }).then(() => { a.show('Asked the bank to move it back to your free balance.'); onDone(); })} />
      {a.toast}
    </div>
  );
}

/** What the API returns for GET /v1/account (FR-ESC-025): one account, its balances and its commitments. */
export type Account = {
  id: string; reference: string; country: string; status: string; client_name: string; bank_name: string; seal: string;
  pay_in: Any; balances: Any[]; free_balance_lines: Any[]; commitments: Commitment[]; closed_commitments: number; countries?: string[];
};
export type Commitment = {
  id: string; reference: string; kind: string; title: string; status: string; currency: string;
  agreed: Any; set_aside: Any; paid_out: Any; on_its_way_in: Any; still_to_set_aside: Any; available_to_instruct: Any;
  instructed_awaiting_bank: Any; payees: string[]; frozen: boolean; cancelling: boolean; can_fund: boolean;
  can_keep_in_account: boolean; needs_you: boolean; bank_sub_ledger_ref: string | null; bank_position: Any; link: string;
};

const KIND: Record<string, string> = {
  purchase: 'Purchase', construction: 'Building', offplan: 'Off-plan', project_fund: 'Project fund', event: 'Event', repair: 'Repair',
};

/** A commitment's state in plain words, from what the bank holds for it. */
export function commitmentState(c: Commitment): string {
  if (c.frozen) return 'On hold. No money moves until the check is done.';
  if (c.cancelling) return 'Being cancelled. The money goes back to where it came from.';
  if (c.status === 'proposed') return 'Waiting for everyone to accept the terms.';
  if (c.status === 'released') return 'Paid out in full.';
  if (c.status === 'cancelled') return 'Cancelled.';
  if (Number(c.on_its_way_in.amount) > 0) return 'Waiting for the bank to confirm the money set aside.';
  if (Number(c.still_to_set_aside.amount) > 0) return Number(c.set_aside.amount) > 0 ? 'Partly set aside.' : 'Nothing set aside yet.';
  if (c.status === 'ready_to_release') return 'Ready to release on your approval.';
  if (c.status === 'partly_released') return 'Paid in stages, on proof.';
  return 'Set aside. Released only on proof.';
}

export function kindWord(kind: string) {
  return KIND[kind] ?? kind;
}

export function useAccount(country?: string) {
  const q = useGet<Account>('/v1/account', country ? { country } : undefined, { shouldRetryOnError: false });
  const missing = q.error instanceof ApiError && q.error.problem.status === 404;
  return { ...q, missing };
}

/** One commitment inside the account card: the deal, what is set aside, and its state. */
function CommitmentRow({ c }: { c: Commitment }) {
  const amount = Number(c.set_aside.amount) > 0 ? c.set_aside : c.agreed;
  return (
    <Link href={`/money/commitments/${c.id}`} className="acct-commit" role="listitem">
      <span style={{ minWidth: 0 }}>
        <span className="acct-commit-kind">{kindWord(c.kind)}{c.needs_you ? <span className="acct-needs"> · needs you</span> : null}</span>
        <span className="acct-commit-title">{c.title}</span>
        <span className="acct-commit-state">{commitmentState(c)}</span>
      </span>
      <span className="acct-commit-amount">
        <Money value={money(amount.amount, amount.currency)} />
        <span className="acct-commit-state">{Number(c.set_aside.amount) > 0 ? 'set aside' : 'agreed'}</span>
      </span>
    </Link>
  );
}

/** 03 6.1a: one account card on black with the seal. The balance, the free balance and the commitments inside it.
 * Never a wallet and never a payment card: the bank holds the money; Tenmina never does (RUL-01). */
export function AccountCard({ holder, max = 4, openIfMissing = false }: { holder: string; max?: number; openIfMissing?: boolean }) {
  const q = useAccount();
  const country = useCountry();
  const a = useAction();
  if (q.isLoading) return <div className="acct-one"><Skeleton lines={4} /></div>;
  if (q.missing) {
    if (!openIfMissing) return null;
    return (
      <section className="acct-one stack" aria-label="Your Tenmina account">
        <div className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
          <div><div className="acct-label">Your Tenmina account</div><div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>One account at the bank for everything at home.</div></div>
          <Seal />
        </div>
        <p style={{ margin: 0, color: '#a9a69e' }}>A licensed bank holds it, not Tenmina. School fees, care, building stages and land purchases are all paid from it, only on proof and after you approve.</p>
        <Button variant="primary" busy={a.busy === 'open'} onClick={() => a.run('open', () => a.post('/v1/account', { country: country.code }), 'Your account is open', () => q.mutate())}>Open my account</Button>
        <ProblemBox error={a.error} />
        {a.toast}
      </section>
    );
  }
  if (!q.data) return <ProblemBox error={q.error} />;
  const acc = q.data;
  const open = acc.commitments.filter((c) => !['released', 'cancelled'].includes(c.status) || Number(c.set_aside.amount) > 0);
  const shown = open.slice(0, max);
  const main = acc.balances[0];
  return (
    <section className="acct-one" aria-label="Your Tenmina account">
      <Link href="/money" className="acct-head">
        <div style={{ minWidth: 0 }}>
          <div className="acct-label">Your Tenmina account</div>
          <div className="mono" style={{ fontSize: 13 }}>{acc.pay_in?.reference ?? acc.reference}</div>
        </div>
        <Seal />
      </Link>
      <div className="acct-label" style={{ marginTop: 6 }}>Held at the bank for you</div>
      {acc.balances.map((b) => (
        <div key={b.currency} className="acct-total"><Money value={b.held_at_bank} /></div>
      ))}
      {main ? (
        <div className="acct-split">
          <div><div className="acct-label">Free balance</div><div className="acct-fig">{acc.balances.map((b) => <div key={b.currency}><Money value={b.free_balance} /></div>)}</div></div>
          <div><div className="acct-label">Set aside</div><div className="acct-fig">{acc.balances.map((b) => <div key={b.currency}><Money value={b.set_aside} /></div>)}</div></div>
        </div>
      ) : null}
      {shown.length ? (
        <div className="stack" style={{ gap: 0 }}>
          <div className="acct-label" style={{ marginTop: 12 }}>Commitments inside it · {open.length}</div>
          <div role="list">{shown.map((c) => <CommitmentRow key={c.id} c={c} />)}</div>
          {open.length > shown.length ? <Link href="/money" className="acct-more">See all {open.length} commitments</Link> : null}
        </div>
      ) : null}
      <div className="acct-foot">
        <span>{holder.toUpperCase()}</span>
        <span style={{ color: '#a9a69e' }}>{(acc.pay_in?.bank_name ?? acc.bank_name ?? '').replace(/\s*\[TO VERIFY\]/, '')}</span>
      </div>
      <div className="acct-actions">
        <Link className="btn btn-sm acct-btn" href="/money/pay-in">How to pay in</Link>
        <Link className="btn btn-sm acct-btn" href="/money">Open the account</Link>
      </div>
    </section>
  );
}
