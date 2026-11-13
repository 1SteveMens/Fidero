'use client';
/* Prices, currencies and rate comparison · SCR-BO-19 (FR-ESC-024, RUL-35): today's comparison for each corridor
 * as a plain dense table with no colour on any rate; the bank's written programme rate with its date; programme
 * accounts (administrators); rate observations entered by hand; conversions outside the programme margin. */
import Link from 'next/link';
import { useMemo } from 'react';
import { Button, call, Empty, ProblemBox, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, Head, money, Panel, useAct, words } from '@/components/core/kit';
import type { Approval, Page } from '@/components/core/types';

type Run = { run_id: string; run_date: string; pair: string; send_amount: string; status: string; providers_expected: number; providers_fresh: number; reference_rate: string | null; last_success_at: string | null; items: { provider: string; kind: string; stale: boolean; rank: number; rate: string; margin_pct: string; fees_total: string; delivered_amount: string; collected_at: string; method: string }[]; bank_best_rate: boolean; statement: string };
type Rate = { id: string; bank_partner: string; from_currency: string; to_currency: string; band_from: string; band_to: string | null; margin_pct: string; tolerance_pct: string; fee_schedule: { name: string; amount: string; currency: string }[]; reference_source: string; valid_from: string; valid_to: string | null; approval_request: string | null; status: string };
type Account = { id: string; bank_partner: string; currency: string; kind: string; holder: string; account_name: string; account_last4: string; approval_request: string | null; status: string; opened_on: string | null };
type Partner = { id: string; name: string; kind: string; status: string };
type Conversion = { id: string; escrow: string; route: string; from_amount: string; to_amount: string; applied_rate: string; margin_pct: string | null; status: string; created_at: string };

function ApproveOne({ path, label, onDone }: { path: string; label: string; onDone: () => void }) {
  return <ActionForm label={label} variant="primary" path={path} stepUp body={() => ({ decision: 'approve' })} onDone={onDone} submitLabel="Approve" intro="A second administrator approves (ADR-16). You cannot approve what you prepared." />;
}

export default function FxPage() {
  const { client, hasRole } = useSession();
  const cmp = useGet<Run[]>('/v1/fx/comparison', { country: 'GH' });
  const rates = useGet<Rate[]>(hasRole('AD', 'CM', 'RV') ? '/v1/admin/programme-rates' : null);
  const accounts = useGet<Account[]>(hasRole('AD') ? '/v1/admin/programme-accounts' : null);
  const partners = useGet<Page<Partner>>(hasRole('AD') ? '/v1/admin/partners' : null, { limit: 100 });
  const outside = useGet<Page<Conversion>>('/v1/fx-conversions', { status: 'outside' });
  const open = useGet<Page<Approval>>(hasRole('AD') ? '/v1/approvals' : null, { status: 'open' });
  const act = useAct();
  const name = useMemo(() => new Map((partners.data?.items ?? []).map((p) => [p.id, p.name])), [partners.data]);
  const opt = (kind: string) => (partners.data?.items ?? []).filter((p) => p.kind === kind && p.status === 'active').map((p) => ({ value: p.id, label: p.name }));
  const isOpen = (reqId: string | null) => !!reqId && (open.data?.items ?? []).some((a) => a.id === reqId);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/escrow', label: 'Escrow' }} title="Rates and accounts" sub="Tenmina takes no margin on the exchange. “Best rate” is said only when the day's comparison is complete and shows it." actions={hasRole('AD', 'CM') ? <Button variant="dark" size="sm" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', '/v1/admin/fx-collections', { country: 'GH' }).then(() => cmp.mutate()), 'Rates collected.')}>Collect today&apos;s rates now</Button> : null} />
      <ProblemBox error={act.error} />
      <Panel title="Today's comparison">
        <ProblemBox error={cmp.error} />
        {cmp.isLoading ? <Skeleton /> : cmp.data?.length ? cmp.data.map((r) => (
          <div key={r.run_id} className="stack" style={{ gap: 6 }}>
            <div className="spread"><strong className="mono">{r.pair} · send {r.send_amount}</strong><span className="mono muted" style={{ fontSize: 12 }}>{day(r.run_date)} · reference {r.reference_rate ?? '—'} · {r.providers_fresh} of {r.providers_expected} providers</span></div>
            <div className="table-wrap">
              <table className="table responsive">
                <thead><tr><th>Provider</th><th>Rate</th><th>Margin</th><th>Fees</th><th>Delivered</th><th>Collected</th></tr></thead>
                <tbody>
                  {r.items.map((it) => (
                    <tr key={it.provider}>
                      <td data-label="Provider">{it.rank}. {it.provider}{it.kind === 'programme' ? ' (bank)' : ''}{it.stale ? ' · stale' : ''}</td>
                      <td data-label="Rate" className="mono">{it.rate}</td><td data-label="Margin" className="mono">{it.margin_pct}%</td>
                      <td data-label="Fees" className="mono">{it.fees_total}</td><td data-label="Delivered" className="mono">{it.delivered_amount}</td>
                      <td data-label="Collected" className="mono">{dayTime(it.collected_at)} · {it.method}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted" style={{ fontSize: 14 }}>{r.statement}</div>
          </div>
        )) : <Empty>No comparison collected today.</Empty>}
        {hasRole('AD', 'CM', 'RV') && partners.data ? (
          <ActionForm label="Enter a rate by hand" path="/v1/admin/fx-observations" upload={{ subject_type: 'fx_observation', subject_id: '00000000-0000-0000-0000-000000000000', country: 'GH', role: 'rate_proof' }} fields={[
            { name: 'source_partner_id', label: 'Source', type: 'select', required: true, options: [...opt('rate_source'), ...opt('transfer_partner'), ...opt('escrow_bank')] },
            { name: 'kind', label: 'Kind', type: 'select', required: true, options: ['reference', 'programme', 'provider'].map((x) => ({ value: x, label: words(x) })) },
            { name: 'from_currency', label: 'From', initial: 'USD', required: true }, { name: 'to_currency', label: 'To', initial: 'GHS', required: true },
            { name: 'rate', label: 'Rate', type: 'number', required: true }, { name: 'send_amount', label: 'Send amount', type: 'money' }, { name: 'fees_total', label: 'Fees', type: 'money' }, { name: 'delivered_amount', label: 'Delivered', type: 'money' },
            { name: 'proof_evidence_id', label: 'Screenshot or page as proof', type: 'file', required: true },
          ]} body={(v) => ({ country: 'GH', source_partner_id: v.source_partner_id, kind: v.kind, from_currency: String(v.from_currency).toUpperCase(), to_currency: String(v.to_currency).toUpperCase(), rate: v.rate, proof_evidence_id: v.proof_evidence_id, ...(v.send_amount ? { send_amount: v.send_amount } : {}), ...(v.fees_total ? { fees_total: v.fees_total } : {}), ...(v.delivered_amount ? { delivered_amount: v.delivered_amount } : {}) })}
            onDone={() => cmp.mutate()} submitLabel="Save" intro="A second person checks it before it counts." />
        ) : null}
      </Panel>

      <Panel title="Conversions outside the programme margin">
        {outside.isLoading ? <Skeleton /> : outside.data?.items.length ? (
          <div className="rows">
            {outside.data.items.map((c) => (
              <Link key={c.id} href={`/escrow/${c.escrow}?tab=fx`} className="rowlink">
                <div className="main"><div className="strip-ink" style={{ display: 'inline-flex', padding: '4px 10px', fontSize: 13 }}>Outside programme margin</div><div className="meta mono">{c.from_amount} → {c.to_amount} at {c.applied_rate}{c.margin_pct ? ` · margin ${c.margin_pct}%` : ''} · {dayTime(c.created_at)}</div></div>
                <span className="chip">{words(c.route)}</span>
              </Link>
            ))}
          </div>
        ) : <Empty>Every checked conversion is within the programme margin.</Empty>}
      </Panel>

      <Panel title="Programme rates (the bank's written rate)" actions={hasRole('AD') && partners.data ? (
        <ActionForm label="+ New programme rate" path="/v1/admin/programme-rates" upload={{ subject_type: 'programme_rate', subject_id: '00000000-0000-0000-0000-000000000000', country: 'GH', role: 'agreement' }} fields={[
          { name: 'bank_partner_id', label: 'Bank', type: 'select', required: true, options: opt('escrow_bank') }, { name: 'reference_source_id', label: 'Reference rate source', type: 'select', required: true, options: opt('rate_source') },
          { name: 'from_currency', label: 'From', initial: 'USD', required: true }, { name: 'to_currency', label: 'To', initial: 'GHS', required: true },
          { name: 'margin_pct', label: 'Margin %', type: 'number', required: true }, { name: 'tolerance_pct', label: 'Tolerance %', type: 'number', initial: '0' },
          { name: 'fee_name', label: 'Fee name' }, { name: 'fee_amount', label: 'Fee amount', type: 'money' },
          { name: 'valid_from', label: 'Valid from', type: 'date', required: true }, { name: 'valid_to', label: 'Valid to', type: 'date' },
          { name: 'agreement_evidence_id', label: "The bank's written rate", type: 'file', required: true },
        ]} body={(v) => ({ country: 'GH', bank_partner_id: v.bank_partner_id, reference_source_id: v.reference_source_id, from_currency: String(v.from_currency).toUpperCase(), to_currency: String(v.to_currency).toUpperCase(), margin_pct: v.margin_pct, tolerance_pct: v.tolerance_pct || 0, fee_schedule: v.fee_name ? [{ name: v.fee_name, amount: v.fee_amount || '0', currency: String(v.from_currency).toUpperCase() }] : [], valid_from: v.valid_from, valid_to: v.valid_to || null, agreement_evidence_id: v.agreement_evidence_id })}
          onDone={() => rates.mutate()} submitLabel="Prepare" intro="A second administrator approves before it is used." />
      ) : null}>
        {rates.isLoading ? <Skeleton /> : rates.data?.length ? (
          <div className="rows">
            {rates.data.map((r) => (
              <div key={r.id} className="rowlink">
                <div className="main">
                  <div className="title mono">{r.from_currency}/{r.to_currency} · margin {r.margin_pct}% · tolerance {r.tolerance_pct}%</div>
                  <div className="meta">{name.get(r.bank_partner) ?? 'Partner bank'} · from {day(r.valid_from)}{r.valid_to ? ` to ${day(r.valid_to)}` : ''} · fees {r.fee_schedule.map((f) => `${f.name} ${money(f.amount, f.currency)}`).join(', ') || 'none'}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <span className="chip">{words(r.status)}</span>
                  {hasRole('AD') && r.status === 'pending' && isOpen(r.approval_request) ? <ApproveOne path={`/v1/admin/programme-rates/${r.id}/approvals`} label="Approve" onDone={() => { rates.mutate(); open.mutate(); }} /> : null}
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>No programme rate on file.</Empty>}
      </Panel>

      {hasRole('AD') ? (
        <Panel title="Programme accounts at the bank" actions={partners.data ? (
          <ActionForm label="+ New account" path="/v1/admin/programme-accounts" upload={{ subject_type: 'programme_account', subject_id: '00000000-0000-0000-0000-000000000000', country: 'GH', role: 'agreement' }} fields={[
            { name: 'bank_partner_id', label: 'Bank', type: 'select', required: true, options: opt('escrow_bank') }, { name: 'currency', label: 'Currency', initial: 'GHS', required: true },
            { name: 'kind', label: 'Kind', type: 'select', initial: 'programme', options: [{ value: 'programme', label: 'Programme account' }, { value: 'single_escrow', label: 'Single escrow account' }] },
            { name: 'account_number', label: 'Account number', required: true }, { name: 'account_name', label: 'Account name', required: true },
            { name: 'agreement_evidence_id', label: 'The three-party agreement', type: 'file', required: true },
          ]} body={(v) => ({ country: 'GH', bank_partner_id: v.bank_partner_id, currency: String(v.currency).toUpperCase(), kind: v.kind || 'programme', account_number: v.account_number, account_name: v.account_name, agreement_evidence_id: v.agreement_evidence_id })}
            onDone={() => accounts.mutate()} submitLabel="Prepare" intro="The bank holds the money as escrow agent. Tenmina never holds client money." />
        ) : null}>
          {accounts.isLoading ? <Skeleton /> : accounts.data?.length ? (
            <div className="rows">
              {accounts.data.map((a) => (
                <div key={a.id} className="rowlink">
                  <div className="main"><div className="title">{a.account_name}</div><div className="meta">{a.currency} · {words(a.kind)} · {words(a.holder)} · ending <span className="mono">{a.account_last4}</span> · opened {day(a.opened_on)}</div></div>
                  <div className="row" style={{ gap: 6 }}>
                    <span className="chip">{words(a.status)}</span>
                    {a.status === 'pending' && isOpen(a.approval_request) ? <ApproveOne path={`/v1/admin/programme-accounts/${a.id}/approvals`} label="Approve" onDone={() => { accounts.mutate(); open.mutate(); }} /> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : <Empty>No programme accounts.</Empty>}
        </Panel>
      ) : null}
      {act.toast}
    </div>
  );
}
