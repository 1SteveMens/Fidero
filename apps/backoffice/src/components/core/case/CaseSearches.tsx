'use client';
/* Official search record · SCR-BO-43 (FR-CASE-016, RUL-30). One record per search: registry and channel, the
 * Tenmina account used, who submitted it, the registry's reference, the result as received from that channel.
 * A copy someone hands over is noted in muted text, never as evidence. */
import { Empty, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, iso, Panel, str, words } from '../kit';
import type { CaseDetail, SearchRequest } from '../types';

const CHANNEL: Record<string, string> = { online_portal: 'Lands Commission online portal', registry_office: 'Registry office (client service unit)' };

export function CaseSearches({ c, reload }: { c: CaseDetail; reload: () => void }) {
  const list = useGet<SearchRequest[]>(`/v1/cases/${c.id}/search-requests`);
  const searchTasks = (c.tasks ?? []).filter((t) => t.search_kind && t.status !== 'cancelled');
  const refresh = () => { list.mutate(); reload(); };
  return (
    <Panel title="Official searches" actions={searchTasks.length ? (
      <ActionForm label="+ Record a search lodged" path={`/v1/cases/${c.id}/search-requests`} title="Record a search lodged from Tenmina's registry account" fields={[
        { name: 'task_id', label: 'Search task', type: 'select', required: true, options: searchTasks.map((t) => ({ value: t.id, label: t.title })) },
        { name: 'channel', label: 'Channel', type: 'select', required: true, options: Object.entries(CHANNEL).map(([value, label]) => ({ value, label })) },
        { name: 'tenmina_account_ref', label: "Tenmina's registry account", required: true },
        { name: 'registry_reference', label: "Registry's reference" },
        { name: 'search_on', label: 'What was searched (plot, site plan, title)' },
        { name: 'submitted_at', label: 'Lodged at', type: 'datetime' },
      ]} body={(v) => ({ task_id: v.task_id, channel: v.channel, tenmina_account_ref: v.tenmina_account_ref, registry_reference: v.registry_reference || '', search_on: v.search_on || '', submitted_at: iso(v.submitted_at) })}
        onDone={refresh} submitLabel="Save record" intro="Only searches lodged by staff from Tenmina's own registry account count (RUL-30)." />
    ) : null}>
      <div className="notice">A result someone hands over (a runner, the seller, an agent or the client) never closes a search. Tenmina must have the same result from the registry&apos;s own channel.</div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton /> : list.data?.length ? (
        <div className="rows">
          {list.data.map((s) => (
            <div key={s.id} className="card stack" style={{ background: 'var(--color-bg)', padding: 14 }}>
              <div className="spread">
                <div>
                  <div className="label">{CHANNEL[s.channel] ?? words(s.channel)}{s.registry ? ` · ${s.registry}` : ''}</div>
                  <div style={{ fontWeight: 700 }}>{s.search_on || 'Official search'}</div>
                </div>
                <span className={`chip ${s.usable ? 'chip-lime' : ''}`}>{s.usable ? '✓ Official record' : words(s.status)}</span>
              </div>
              <dl className="facts">
                <div><dt>Tenmina account</dt><dd className="mono">{s.tenmina_account_ref}</dd></div>
                <div><dt>Lodged by</dt><dd>{s.submitted_by?.name ?? '—'}, {dayTime(s.submitted_at)}</dd></div>
                <div><dt>Registry reference</dt><dd className="mono">{s.registry_reference || '—'}</dd></div>
                <div><dt>Result dated</dt><dd className="mono">{day(s.registry_result_date)}</dd></div>
                <div><dt>Received by</dt><dd>{s.result_received_by ? `${s.result_received_by.name}, ${dayTime(s.result_received_at)}` : '—'}</dd></div>
                <div><dt>Confirmed with registry</dt><dd>{s.confirmed_by ? `${s.confirmed_with} by ${s.confirmed_by.name}, ${dayTime(s.confirmed_at)}` : '—'}</dd></div>
              </dl>
              {s.result_summary ? <p style={{ margin: 0 }}>{s.result_summary}</p> : null}
              {s.status === 'rejected' ? <p className="muted" style={{ margin: 0 }}>Rejected: {s.rejected_reason}</p> : null}
              {s.status !== 'rejected' ? (
                <div className="row">
                  {s.status === 'submitted' ? (
                    <ActionForm label="Record result from the registry" variant="dark" path={`/v1/search-requests/${s.id}/results`} upload={{ subject_type: 'case', subject_id: c.id, role: 'official_search_result' }} fields={[
                      { name: 'evidence_id', label: 'Result as received from the registry channel', type: 'file', required: true },
                      { name: 'registry_result_date', label: 'Date on the result', type: 'date', required: true },
                      { name: 'registry_reference', label: "Registry's reference" },
                      { name: 'summary', label: 'What it says', type: 'textarea' },
                      { name: 'confirmed_with', label: 'Confirmed with (only if the registry has no remote channel)' },
                      { name: 'confirmed_at', label: 'Confirmed at', type: 'datetime' },
                    ]} body={(v) => ({ evidence_id: v.evidence_id, registry_result_date: v.registry_result_date, registry_reference: v.registry_reference || '', summary: v.summary || '', confirmed_with: str(v.confirmed_with), confirmed_at: iso(v.confirmed_at) })}
                      onDone={refresh} submitLabel="Save result" />
                  ) : null}
                  {s.status === 'result_received' && !s.confirmed_by ? (
                    <ActionForm label="Confirm with the registry" path={`/v1/search-requests/${s.id}/confirmations`} fields={[
                      { name: 'confirmed_with', label: 'Who at the registry', required: true }, { name: 'confirmed_at', label: 'When', type: 'datetime', required: true },
                    ]} body={(v) => ({ confirmed_with: v.confirmed_with, confirmed_at: iso(v.confirmed_at) })} onDone={refresh} submitLabel="Save" />
                  ) : null}
                  <ActionForm label="Note a handed-over copy" path={`/v1/search-requests/${s.id}/copy-comparisons`} upload={{ subject_type: 'case', subject_id: c.id, role: 'handed_over_copy' }} fields={[
                    { name: 'evidence_id', label: 'The copy someone handed over', type: 'file', required: true },
                    { name: 'matches', label: 'It matches the official result', type: 'checkbox' },
                    { name: 'note', label: 'Who handed it over and what differs', type: 'textarea' },
                  ]} body={(v) => ({ evidence_id: v.evidence_id, matches: !!v.matches, note: v.note || '' })} onDone={refresh} submitLabel="Save note" intro="Handed over, not evidence. This never closes the search task." />
                  <ActionForm label="Reject" path={`/v1/search-requests/${s.id}/rejections`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={refresh} submitLabel="Reject record" />
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : <Empty>{searchTasks.length ? 'No search lodged yet.' : 'This case has no search step.'}</Empty>}
    </Panel>
  );
}
