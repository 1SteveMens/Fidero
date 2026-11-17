'use client';
/* Client account · SCR-BO-46: the client's one Tenmina account at the bank (decision 2026-11-17, FR-ESC-025 to 028).
 * Pay-in details, the balance per currency against the bank's own figure, the free balance, and every commitment
 * inside it with what the bank holds for it and the bank's position for it. Read only: money moves on each line. */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Empty, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { day, Facts, Head, money, Panel, words } from '@/components/core/kit';
import type { Account } from '@/components/core/types';

export default function AccountPage() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Account>(`/v1/accounts/${id}`);
  if (q.isLoading) return <Skeleton lines={8} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const a = q.data;
  const lines = a.pay_in.lines ?? [];
  const open = a.commitments.filter((c) => !['released', 'cancelled'].includes(c.status) || Number(c.set_aside.amount) > 0);
  const done = a.commitments.filter((c) => !open.includes(c));
  return (
    <div className="stack" style={{ gap: 16 }}>
      <Head crumb={{ href: '/escrow?tab=accounts', label: 'Accounts' }} title={`${a.client_name}'s Tenmina account`}
        chips={<><span className="chip mono">{a.reference}</span><span className="chip">{a.country} · {words(a.status)}</span></>}
        sub={`Opened ${day(a.opened_at)}. Held by ${a.bank_name}, never by Tenmina. The bank keeps each commitment apart.`} />

      <div className="grid2">
        <Panel title="Pay-in details the client sees">
          {a.pay_in.available ? (
            <Facts items={[
              ['Bank', String(a.pay_in.bank_name ?? '')],
              ['Pay-in reference', <span key="r" className="mono">{String(a.pay_in.reference ?? '')}</span>],
              ...lines.map((l) => [`${l.currency} account`, <span key={l.currency} className="mono">{l.account_name} · {l.account_number}</span>] as [string, React.ReactNode]),
            ]} />
          ) : <p className="muted" style={{ margin: 0 }}>{String(a.pay_in.message ?? 'No pay-in details yet.')}</p>}
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>One set of details for everything. A commitment has no pay-in details of its own.</p>
        </Panel>
        <Panel title="Balance and the bank's position">
          {a.balances.map((b) => (
            <div key={b.currency} className="stack" style={{ gap: 6 }}>
              <Facts items={[
                ['Held at the bank', <strong key="h">{money(b.held_at_bank.amount, b.currency)}</strong>],
                ['Free balance', money(b.free_balance.amount, b.currency)],
                ['Set aside in commitments', money(b.set_aside.amount, b.currency)],
                ['Instructed, waiting for the bank', money(b.instructed_awaiting_bank.amount, b.currency)],
                ["Bank's latest figures", `${money(b.bank_position.reported.amount, b.currency)} for ${b.bank_position.lines_reported} of ${b.bank_position.lines} lines`],
              ]} />
              {b.bank_position.mismatch ? <span className="chip chip-ink" style={{ whiteSpace: 'normal', height: 'auto' }}>The bank&apos;s figure differs on a line. Releases there are blocked (RUL-34).</span>
                : b.bank_position.complete ? <span className="chip chip-lime">✓ The bank reported every line</span> : <span className="chip">Not every line has a bank figure yet</span>}
            </div>
          ))}
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>Derived from bank-confirmed events only. Nobody edits these figures.</p>
        </Panel>
      </div>

      <Panel title={`Commitments inside the account · ${open.length}`}>
        {open.length ? (
          <div className="rows">
            {open.map((c) => (
              <Link key={c.id} href={`/escrow/${c.id}`} className="rowlink">
                <div className="main">
                  <div className="mono" style={{ fontSize: 12 }}>{c.reference} · {words(c.kind)} · sub-ledger {c.bank_sub_ledger_ref ?? 'not issued'}</div>
                  <div className="title">{c.title}</div>
                  <div className="meta">Set aside {money(c.set_aside.amount, c.currency)} of {money(c.agreed.amount, c.currency)} · paid out {money(c.paid_out.amount, c.currency)}{Number(c.on_its_way_in.amount) > 0 ? ` · ${money(c.on_its_way_in.amount, c.currency)} on its way in` : ''}{Number(c.still_to_set_aside.amount) > 0 ? ` · ${money(c.still_to_set_aside.amount, c.currency)} still to set aside` : ''}</div>
                  <div className="meta">Pays only {c.payees.length ? c.payees.join(', ') : 'a payee named in its terms'} · bank figure {c.bank_position ? `${money(c.bank_position.reported.amount, c.currency)} on ${day(c.bank_position.as_of)} (${words(c.bank_position.status)})` : 'not reported yet'}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {c.frozen ? <span className="chip chip-ink">🔒 Frozen</span> : <span className="chip">{words(c.status)}</span>}
                  {c.cancelling ? <span className="chip">Cancelling</span> : null}
                  {c.needs_you ? <span className="chip">Waiting for the client</span> : null}
                </div>
              </Link>
            ))}
          </div>
        ) : <Empty>No open commitment.</Empty>}
      </Panel>

      <Panel title="Free balance lines">
        <div className="rows">
          {a.free_balance_lines.map((l) => (
            <Link key={l.id} href={`/escrow/${l.id}`} className="rowlink">
              <div className="main"><div className="mono" style={{ fontSize: 12 }}>{l.reference} · {l.virtual_account_ref ?? 'no reference'}</div><div className="title">{l.currency} free balance</div><div className="meta">Held {money(l.held_at_bank.amount, l.currency)} · free to instruct {money(l.available_to_instruct.amount, l.currency)}</div></div>
              <span className="chip">{words(l.status)}</span>
            </Link>
          ))}
        </div>
      </Panel>

      {done.length ? (
        <Panel title={`Finished commitments · ${done.length}`}>
          <div className="rows">
            {done.map((c) => (
              <Link key={c.id} href={`/escrow/${c.id}`} className="rowlink"><div className="main"><div className="mono" style={{ fontSize: 12 }}>{c.reference} · {words(c.kind)}</div><div className="title">{c.title}</div><div className="meta">Paid out {money(c.paid_out.amount, c.currency)}</div></div><span className="chip">{words(c.status)}</span></Link>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
