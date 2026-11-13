'use client';
/* SCR-BO-23 Dashboard and exports. The A9 dashboard reads /v1/analytics once that module
 * lands; until then this page shows what is already measured and lists what will come. */
import React from 'react';
import { Empty, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { formatMoney } from '@tenmina/api-client';
import { humanize } from './fmt';
import type { Row } from './spec';
import './ops.css';

const A9 = [
  'Paid reports per month, by tier and country',
  'Turnaround, median and 90th percentile, payment to delivery',
  'Time per workflow step against target',
  'Cost per report',
  'Verdict mix: red, amber, green',
  'Conversion: report to escrow, report to build',
  'Lead source and conversion',
  'Escrows opened, value held at the bank, value released',
  'Milestones submitted, passed first time, failed, flagged for fraud',
  'Listings live, views, enquiries, sales through escrow',
  'Payments to institutions per month, value, share with receipt returned within target',
  'Care visits scheduled, completed, confirmed by family',
  'Properties under management, rent collected, repairs completed',
  'Errands completed, median days to completion',
  'Policies sold through insurer partners, claims paid',
  'Disputes opened, resolved within the timeline',
  'Client satisfaction (would recommend, yes or no)',
  'Safety incidents',
];

const SHOWN: [string, string][] = [
  ['ord_order', 'Orders'], ['case_case', 'Cases'], ['esc_escrow', 'Escrows'], ['fee_invoice', 'Bills to institutions'],
  ['care_visit', 'Care visits'], ['tsk_errand', 'Errands'], ['pmg_managed_property', 'Managed properties'], ['lst_listing', 'Listings'],
  ['dsp_dispute', 'Disputes'], ['ins_policy', 'Policies'], ['evd_evidence', 'Evidence files'],
];

export function AnalyticsPage() {
  const cost = useGet<Row>('/v1/cost-per-report');
  const metrics = useGet<Row[]>('/v1/countries/metrics');
  return (
    <div className="stack ops">
      <div>
        <p className="label">SCR-BO-23 · FR-ANL-001 to FR-ANL-003</p>
        <h1>Analytics</h1>
        <p className="muted" style={{ maxWidth: 720 }}>The operating dashboard with the A9 metrics, by date, country, product line and tier, with CSV export. It is being built now; this page shows what is already measured.</p>
      </div>

      <section className="stack">
        <h2 style={{ margin: 0 }}>Cost per report</h2>
        {cost.error ? <ProblemBox error={cost.error} /> : cost.isLoading ? <Skeleton lines={2} /> : cost.data ? (
          <div className="grid3">
            <div className="card"><div className="label">Reports costed</div><div className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{String(cost.data.reports ?? 0)}</div></div>
            {Object.entries((cost.data.per_report as Record<string, string>) ?? {}).map(([cur, amt]) => (
              <div key={cur} className="card"><div className="label">Per report, {cur}</div><div className="money" style={{ fontSize: 28, fontWeight: 800 }}>{formatMoney({ amount: amt, currency: cur })}</div><small className="muted">From case costs entered by operations</small></div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="stack">
        <h2 style={{ margin: 0 }}>Records by country</h2>
        {metrics.error ? <ProblemBox error={metrics.error} /> : metrics.isLoading ? <Skeleton /> : (metrics.data ?? []).length ? (
          <div className="table-wrap">
            <table className="table responsive ops-table">
              <thead><tr><th>Country</th>{SHOWN.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
              <tbody>
                {(metrics.data ?? []).map((c) => (
                  <tr key={String(c.country)}>
                    <td data-label="Country"><strong>{String(c.name)}</strong> <span className="chip">{humanize(String(c.status))}</span></td>
                    {SHOWN.map(([k, l]) => <td key={k} data-label={l} className="mono">{String((c.counts as Record<string, number>)?.[k] ?? 0)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>No countries yet.</Empty>}
      </section>

      <section className="stack">
        <h2 style={{ margin: 0 }}>Coming to this dashboard (A9)</h2>
        <ul className="ops-checklist">
          {A9.map((m) => <li key={m}><span className="tick" aria-hidden /><span>{m}</span></li>)}
        </ul>
        <p className="muted" style={{ margin: 0 }}>Every metric filterable by country, with CSV export logged. No personal data beyond what your role allows.</p>
      </section>
    </div>
  );
}
