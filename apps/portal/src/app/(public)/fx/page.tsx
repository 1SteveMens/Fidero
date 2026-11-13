/* Today's exchange rate comparison (FR-ESC-024, US-ESC-024, 5.6e): providers ranked by the amount
   delivered after all fees. "Best rate" is said only on a complete day. Figures come from the providers
   and the partner bank; they are working figures, not advice. */
import type { Metadata } from 'next';
import { apiGet } from '@/components/roles/server-api';

export const dynamic = 'force-dynamic';
export const metadata: Metadata = { title: 'Today’s exchange rates | Tenmina', description: 'How many cedis each provider delivers today, after every fee.' };

type Item = { provider: string; kind: string; stale: boolean; rank: number | null; rate: string; margin_pct: string; fees_total: string; delivered_amount: string; collected_at: string };
type Run = { run_id: string; run_date: string; pair: string; send_amount: string; status: string; providers_expected: number; providers_fresh: number; reference_rate: string; items: Item[]; bank_best_rate: boolean; statement: string };

const n = (s: string, d = 2) => Number(s).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });

export default async function FxPage({ searchParams }: { searchParams: Promise<{ country?: string }> }) {
  const sp = await searchParams;
  const { data, status } = await apiGet<Run[]>('/v1/fx/comparison', { country: sp.country || 'GH' });
  const runs = data ?? [];
  return (
    <div className="stack">
      <div>
        <p className="label" style={{ margin: 0 }}>Exchange rates</p>
        <h1>Today&apos;s comparison</h1>
        <p className="muted">How much arrives for each amount sent, after every fee. Tenmina takes no margin on the exchange.</p>
      </div>
      {status >= 400 ? <div className="error-box" role="alert"><strong>We could not load today&apos;s rates.</strong><div>Try again later.</div></div> : null}
      {status < 400 && !runs.length ? <div className="card muted">No comparison has run today yet.</div> : null}
      {runs.map((r) => {
        const [from, to] = r.pair.split('/');
        return (
          <section key={r.run_id} className="card stack">
            <div className="spread">
              <h2 style={{ margin: 0 }}>{from} {n(r.send_amount, 0)} to {to}</h2>
              <span className="chip">{r.status === 'complete' ? 'Complete' : `${r.providers_fresh} of ${r.providers_expected} providers`}</span>
            </div>
            <span className="muted" style={{ fontSize: 14 }}>Reference rate {n(r.reference_rate, 4)} · {new Date(r.run_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}</span>
            {r.items.map((i) => (
              <div key={i.provider} className="stack" style={{ gap: 2, borderTop: '1px solid var(--color-line)', paddingTop: 8 }}>
                <div className="spread">
                  <strong>{i.rank ? `${i.rank}. ` : ''}{i.provider}</strong>
                  <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{to} {n(i.delivered_amount)}</strong>
                </div>
                <span className="muted" style={{ fontSize: 14 }}>Rate {n(i.rate, 4)} · margin {n(String(Number(i.margin_pct)), 2)}% · fees {from} {n(i.fees_total)}{i.stale ? ' · not updated today' : ''}</span>
              </div>
            ))}
            <p style={{ margin: 0, fontSize: 14 }}>{r.statement}</p>
          </section>
        );
      })}
      <p className="muted" style={{ fontSize: 13 }}>Figures are what each provider published at the time shown. Your bank&apos;s own rate may differ.</p>
    </div>
  );
}
