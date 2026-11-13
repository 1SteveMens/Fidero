'use client';
/* My pay (SCR-BO-33 to SCR-BO-36 content, W-40): totals, the account Tenmina pays, jobs, payables,
   expense claims and statements. Only black, white and lime on pay screens; never a verdict or result
   next to an amount (RUL-26, 5.6b). Paid by Tenmina from its own account (RUL-27). */
import Link from 'next/link';
import { useState } from 'react';
import { Chip, Money, ProblemBox, Skeleton, When, useGet } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { EmptyText, PageHead, Section, items, words, type Page } from '@/components/roles/kit';
import { HOLD_TEXT, WORK_KIND, type Payable } from '@/components/roles/work';
import { download } from '@/components/roles/files';

type Agreement = {
  id: string; reference: string; role: string; status: string; valid_from: string; valid_to: string | null; tax_status: string;
  destination: { bank_name: string; account_name: string; account_last4: string; verification_status: string } | null;
  rate_cards: { unit: string; scope_key: string; rate: MoneyT; version: number; valid_from: string }[];
};
type Claim = { id: string; kind: string; description: string; amount: MoneyT; incurred_on: string; status: string; created_at: string; decision_note: string };
type Statement = { id: string; kind: string; line_reference: string | null; tax_year: number | null; gross: MoneyT; withholding: MoneyT; net: MoneyT; issued_at: string };

function sum(list: Payable[], pick: (p: Payable) => MoneyT): MoneyT | null {
  if (!list.length) return null;
  const cur = pick(list[0]).currency;
  return { currency: cur, amount: list.filter((p) => pick(p).currency === cur).reduce((a, p) => a + Number(pick(p).amount), 0).toFixed(2) };
}

const PAY_STATUS: Record<string, string> = {
  accepted: 'Accepted, not yet paid', approved: 'Accepted, not yet paid', in_run: 'In a payment run', paid: 'Paid', held: 'Held', failed: 'Returned by the bank', cancelled: 'Cancelled',
};

export default function MyPay() {
  const ag = useGet<Agreement[]>('/v1/me/pro/agreement');
  const pay = useGet<Page<Payable>>('/v1/me/pro/payables');
  const claims = useGet<Page<Claim>>('/v1/me/pro/expense-claims');
  const docs = useGet<Page<Statement>>('/v1/me/pro/statements');
  const [err, setErr] = useState<unknown>(null);
  const now = new Date();
  const payables = items(pay.data);
  const thisMonth = (d: string | null) => !!d && new Date(d).getMonth() === now.getMonth() && new Date(d).getFullYear() === now.getFullYear();
  const unpaid = payables.filter((p) => !['paid', 'cancelled'].includes(p.status));
  const paidMonth = payables.filter((p) => p.status === 'paid' && thisMonth(p.paid_at));
  const a = ag.data?.[0];

  if (ag.error) return <ProblemBox error={ag.error} />;
  return (
    <div className="stack">
      <PageHead label="My pay" title="My pay">The same amount whatever the result of the work.</PageHead>
      {ag.isLoading || pay.isLoading ? <Skeleton lines={4} /> : null}
      {!ag.isLoading && !a ? <EmptyText>You have no active agreement with Tenmina yet. Your pay shows here once you do.</EmptyText> : null}
      {a ? (
        <div className="card-ink stack">
          <div className="label">{now.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}</div>
          <div className="statline"><span>Accepted, not yet paid</span><span className="v">{unpaid.length ? <Money value={sum(unpaid, (p) => p.net)} /> : '—'}</span></div>
          <div className="statline"><span>Paid this month</span><span className="v">{paidMonth.length ? <Money value={sum(paidMonth, (p) => p.net)} /> : '—'}</span></div>
          <p style={{ margin: 0 }}>Paid by Tenmina, from its own account{a.destination ? <>, to <strong>{a.destination.account_name}</strong>, account ending <span className="mono">{a.destination.account_last4}</span> at {a.destination.bank_name}</> : null}.</p>
          {a.destination && a.destination.verification_status !== 'verified' ? <p style={{ margin: 0 }}>We have not yet confirmed this account. Payments wait until we do.</p> : null}
          <Link href="/work/pay/expenses/new" className="btn btn-primary">Claim an expense</Link>
        </div>
      ) : null}

      <Section title="Jobs and payments">
        {!pay.isLoading && !payables.length ? <EmptyText>No accepted jobs yet.</EmptyText> : null}
        {payables.map((p) => (
          <div key={p.id} className="card stack" style={{ gap: 4 }}>
            <div className="spread">
              <div><div className="label">{p.case_reference ?? words(p.role)}</div><strong>{WORK_KIND[p.work_kind] ?? words(p.work_kind)}</strong></div>
              <div style={{ textAlign: 'right' }}><Money value={p.net} /><div className="muted" style={{ fontSize: 12 }}>after tax</div></div>
            </div>
            <div className="row" style={{ fontSize: 14 }}>
              {p.status === 'paid' ? <Chip tone="lime">✓ Paid</Chip> : <Chip>{PAY_STATUS[p.status] ?? words(p.status)}</Chip>}
              {p.accepted_at ? <span className="muted">Accepted <When value={p.accepted_at} /></span> : null}
              {p.status === 'paid' && p.paid_at ? <span className="muted">Paid <When value={p.paid_at} /></span> : p.due_by ? <span className="muted">Due by <When value={p.due_by} /></span> : null}
            </div>
            {p.status === 'held' ? <span style={{ fontSize: 14 }}>{HOLD_TEXT[p.hold_reason] ?? 'Held. Tenmina will tell you why.'}</span> : null}
            {p.status === 'failed' ? <span style={{ fontSize: 14 }}>Your bank returned the payment. We will pay it in the next run.</span> : null}
            {p.run_reference ? <span className="muted mono" style={{ fontSize: 13 }}>{p.run_reference}</span> : null}
            <span className="muted" style={{ fontSize: 13 }}>Gross <Money value={p.gross} /> · tax withheld <Money value={p.withholding} /></span>
          </div>
        ))}
      </Section>

      <Section title="Expense claims" action={<Link href="/work/pay/expenses/new" className="btn btn-ghost btn-sm">New claim</Link>}>
        {!claims.isLoading && !items(claims.data).length ? <EmptyText>No expense claims.</EmptyText> : null}
        {items(claims.data).map((c) => (
          <div key={c.id} className="card spread">
            <div style={{ minWidth: 0, flex: 1 }}><div className="label">{words(c.kind)} · <When value={c.incurred_on} /></div><strong>{c.description}</strong>{c.decision_note ? <div className="muted" style={{ fontSize: 14 }}>{c.decision_note}</div> : null}</div>
            <div className="rl-right"><Money value={c.amount} />{c.status === 'paid' ? <Chip tone="lime">✓ Paid</Chip> : <Chip>{words(c.status)}</Chip>}</div>
          </div>
        ))}
      </Section>

      <Section title="Statements">
        {!docs.isLoading && !items(docs.data).length ? <EmptyText>No statements yet. A remittance advice comes with each payment.</EmptyText> : null}
        {items(docs.data).map((d) => (
          <div key={d.id} className="card spread">
            <div><div className="label">{d.kind === 'remittance_advice' ? 'Remittance advice' : `Yearly statement ${d.tax_year ?? ''}`} · <When value={d.issued_at} /></div><strong><Money value={d.net} /></strong> <span className="muted" style={{ fontSize: 14 }}>net, tax <Money value={d.withholding} /></span></div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => download(`/v1/me/pro/statements/${d.id}/pdf`, `tenmina-${d.line_reference ?? d.id}.pdf`).catch(setErr)}>PDF</button>
          </div>
        ))}
        <ProblemBox error={err} />
      </Section>

      {a ? (
        <Section title="Your rates">
          <div className="card">
            <p className="muted" style={{ marginTop: 0 }}>Agreement <span className="mono">{a.reference}</span> as {words(a.role)}, from <When value={a.valid_from} />. Rates never depend on the result of the work.</p>
            {a.rate_cards.map((r) => <div key={r.unit + r.scope_key} className="statline"><span>{WORK_KIND[r.unit] ?? words(r.unit)}{r.scope_key !== 'standard' ? ` (${words(r.scope_key)})` : ''}</span><span className="v"><Money value={r.rate} /></span></div>)}
          </div>
        </Section>
      ) : null}
    </div>
  );
}
