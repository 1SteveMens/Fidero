'use client';
/* Costs (FR-CASE-011), risk screens and the safety incident log (FR-CASE-009, FR-CASE-010). The log is
 * readable only by people named as safety readers; everyone on the case can write to it. */
import { ApiError } from '@tenmina/api-client';
import { Empty, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, iso, money, Panel, words } from '../kit';
import type { CaseDetail, Cost, MoneyT, RiskScreen } from '../types';

type Costs = { items: Cost[]; by_item: Record<string, MoneyT[] | Record<string, string> | string>; totals: Record<string, string> };
type Incident = { id: string; severity: string; narrative: string; persons_named: string; location_note: string; occurred_at: string | null; created_at: string; reported_by: string };

export function CaseCosts({ c }: { c: CaseDetail }) {
  const costs = useGet<Costs>(`/v1/cases/${c.id}/costs`);
  const items = costs.data?.items ?? [];
  const totals = costs.data?.totals ?? {};
  return (
    <Panel title="Costs" actions={
      <ActionForm label="+ Add a cost" path={`/v1/cases/${c.id}/costs`} fields={[
        { name: 'item_type', label: 'Item', type: 'select', required: true, options: ['lawyer', 'surveyor', 'runner', 'inspector', 'fees', 'travel', 'other'].map((x) => ({ value: x, label: words(x) })) },
        { name: 'amount', label: 'Amount', type: 'money', required: true },
        { name: 'currency', label: 'Currency', initial: 'GHS', required: true },
        { name: 'incurred_on', label: 'Date', type: 'date' },
        { name: 'description', label: 'Description' },
      ]} body={(v) => ({ item_type: v.item_type, amount: { amount: v.amount, currency: String(v.currency).toUpperCase() }, incurred_on: v.incurred_on || undefined, description: v.description || '' })}
        onDone={() => costs.mutate()} submitLabel="Add cost" intro="Professional pay and expenses fill in on their own from accepted work." />
    }>
      <ProblemBox error={costs.error} />
      {costs.isLoading ? <Skeleton /> : items.length ? (
        <>
          <div className="rows">
            {items.map((i) => (
              <div key={i.id} className="rowlink">
                <div className="main"><div className="title">{words(i.item_type)}</div><div className="meta">{i.description || words(i.source)} · {day(i.incurred_on)}</div></div>
                <span className="mono" style={{ fontWeight: 700 }}>{money(i.amount.amount, i.amount.currency)}</span>
              </div>
            ))}
          </div>
          <div className="spread"><strong>Total</strong><span className="mono" style={{ fontWeight: 800 }}>{Object.entries(totals).map(([cur, amt]) => money(amt, cur)).join(' + ') || '—'}</span></div>
        </>
      ) : <Empty>No costs recorded yet.</Empty>}
    </Panel>
  );
}

export function CaseSafety({ c }: { c: CaseDetail }) {
  const screens = useGet<RiskScreen[]>(`/v1/cases/${c.id}/risk-screens`);
  const log = useGet<Incident[]>(`/v1/safety-incidents`, { case: c.id }, { shouldRetryOnError: false });
  const notReader = log.error instanceof ApiError && (log.error.problem.status === 403 || log.error.problem.status === 404);
  return (
    <div className="cols">
      <Panel title="Risk screens">
        <ProblemBox error={screens.error} />
        {screens.isLoading ? <Skeleton /> : screens.data?.length ? (
          <div className="rows">
            {screens.data.map((s) => (
              <div key={s.id} className="rowlink">
                <div className="main">
                  <div className="title">{s.outcome === 'do_not_visit' ? '✕ Do not visit' : s.outcome === 'proceed_with_two' ? '! Two people needed' : '✓ Clear to visit'}</div>
                  <div className="meta">{s.screened_by?.name} · {dayTime(s.created_at)} · valid until {day(s.valid_until)}{s.disputed_at_screen ? ' · disputed plot' : ''}</div>
                  {s.hazards ? <div style={{ fontSize: 14 }}>{s.hazards}</div> : null}
                </div>
                <span className="chip">{s.people_required} {s.people_required === 1 ? 'person' : 'people'}</span>
              </div>
            ))}
          </div>
        ) : <Empty>No risk screen yet. A site visit cannot be assigned without one.</Empty>}
      </Panel>
      <Panel title="Safety incidents" actions={
        <ActionForm label="Log an incident" variant="dark" path={`/v1/cases/${c.id}/safety-incidents`} fields={[
          { name: 'severity', label: 'How serious', type: 'select', required: true, options: ['low', 'medium', 'high', 'critical'].map((x) => ({ value: x, label: words(x) })) },
          { name: 'narrative', label: 'What happened', type: 'textarea', required: true },
          { name: 'persons_named', label: 'People involved' },
          { name: 'location_note', label: 'Where' },
          { name: 'occurred_at', label: 'When', type: 'datetime' },
        ]} body={(v) => ({ severity: v.severity, narrative: v.narrative, persons_named: v.persons_named || '', location_note: v.location_note || '', occurred_at: iso(v.occurred_at) })}
          onDone={() => log.mutate()} submitLabel="Log incident" intro="The incident goes to the restricted log. The safety lead and the case manager are told. If you are in danger, leave and call the duty phone." />
      }>
        {notReader ? <p className="muted" style={{ margin: 0 }}>Only people named as safety readers can read the log. Anyone on the case can add to it.</p>
          : log.isLoading ? <Skeleton /> : log.data?.length ? (
            <div className="rows">
              {log.data.map((i) => (
                <div key={i.id} className="rowlink">
                  <div className="main"><div className="title">{i.narrative}</div><div className="meta">{dayTime(i.occurred_at ?? i.created_at)}{i.location_note ? ` · ${i.location_note}` : ''}{i.persons_named ? ` · ${i.persons_named}` : ''}</div></div>
                  <span className="chip">{words(i.severity)}</span>
                </div>
              ))}
            </div>
          ) : log.error ? <ProblemBox error={log.error} /> : <Empty>No incidents logged on this case.</Empty>}
      </Panel>
    </div>
  );
}
