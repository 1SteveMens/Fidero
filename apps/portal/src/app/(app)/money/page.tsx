'use client';
import Link from 'next/link';
import { Money, NeedsYou, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { PageHead, Section, list, money, words, type Any } from '@/components/kit';
import { AccountCard, kindWord, commitmentState, useAccount } from '@/components/account-card';

const MOVE: Record<string, string> = {
  deposit: 'Paid in', commitment_debit: 'Set aside', commitment_credit: 'Back from a commitment', release_confirmed: 'Paid out',
  refund_confirmed: 'Refunded to source', conversion_debit: 'Converted', conversion_credit: 'Converted', correction_debit: 'Bank correction',
};

/** SCR-PTL-57 · W-45: the client's one Tenmina account (decision 2026-11-17, FR-ESC-025 to 028). One balance,
 * the free balance, and the commitments inside it. The bank holds it; released only on proof. */
export default function MoneyAccount() {
  const { me } = useSession();
  const acc = useAccount();
  const free = acc.data?.free_balance_lines?.[0];
  const stmt = useGet<Any>(free ? `/v1/escrows/${free.id}/statement` : null);
  const fundable = (acc.data?.commitments ?? []).filter((c) => c.can_fund && Number(c.still_to_set_aside.amount) > 0);
  const closed = (acc.data?.commitments ?? []).filter((c) => ['released', 'cancelled'].includes(c.status) && Number(c.set_aside.amount) <= 0);
  const lines = list(stmt.data?.lines).filter((l: Any) => l.counts).reverse().slice(0, 12);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/', label: 'Home' }} label="Held at the bank · released on proof" title="Your Tenmina account"
        sub="One account at a licensed bank for everything at home. Pay in once. Set money aside for a deal. The bank releases it only on proof, after you approve." />
      {me ? <AccountCard holder={me.full_name} max={50} openIfMissing /> : null}
      {acc.isLoading ? <Skeleton /> : null}
      {fundable.map((c) => (
        <NeedsYou key={c.id} title={`Set aside money for ${c.title}`} detail={`${kindWord(c.kind)}. Still to set aside: ${c.still_to_set_aside.currency} ${Number(c.still_to_set_aside.amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}. ${commitmentState(c)}`} href={`/money/commitments/${c.id}`} />
      ))}
      {acc.data ? (
        <Section title="How it works">
          <div className="card stack" style={{ gap: 8 }}>
            <div><strong>Free balance.</strong> Money you paid in that is not set aside. School fees, care visits, errands and premiums are paid from it, after you approve and two Tenmina staff approve.</div>
            <div><strong>Set aside.</strong> Money committed to one deal: a plot, a build, an event or a repair. The bank keeps it apart. It pays only that deal&apos;s verified payee, when its conditions are met.</div>
            <div><strong>If a deal is cancelled.</strong> The money goes back to the bank account it came from. You can choose to keep it in your Tenmina account instead.</div>
          </div>
        </Section>
      ) : null}
      {lines.length ? (
        <Section title="Free balance: recent movements">
          <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            {lines.map((l: Any) => (
              <div key={l.id} className="check-row" style={{ gridTemplateColumns: '1fr auto' }}>
                <div><div style={{ fontWeight: 600 }}>{l.kind.startsWith('commitment_') && l.subject_label ? l.subject_label : <>{MOVE[l.kind] ?? words(l.kind)}{l.subject_label ? ` · ${l.subject_label}` : ''}</>}</div><div className="mono muted" style={{ fontSize: 12 }}><When value={l.at} /> · {l.bank_reference}</div></div>
                <Money value={money(l.amount, l.currency)} />
              </div>
            ))}
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Only what the bank has confirmed is shown. Tenmina never edits these figures.</p>
        </Section>
      ) : null}
      {closed.length ? (
        <Section title={`Finished commitments · ${closed.length}`}>
          {closed.map((c) => (
            <Link key={c.id} href={`/money/commitments/${c.id}`} className="card card-link spread"><span><span className="label">{kindWord(c.kind)}</span><br /><strong>{c.title}</strong><br /><span className="muted">{commitmentState(c)}</span></span><Money value={c.paid_out} /></Link>
          ))}
        </Section>
      ) : null}
      <ProblemBox error={acc.missing ? null : acc.error} />
      <div className="row">
        <Link className="btn btn-primary" href="/money/pay-in">How to pay in</Link>
      </div>
    </div>
  );
}
