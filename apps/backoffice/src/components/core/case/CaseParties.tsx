'use client';
/* Party identity checks · SCR-BO-44 (FR-ACC-013, RUL-31). One line per seller, grantor, consenting party and
 * signatory: the result from the national identity system, its reference and time. Never a card image. */
import { Empty, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { ActionForm, dayTime, Panel, words } from '../kit';
import type { CaseDetail, Party } from '../types';

export function idState(result?: string | null): { text: string; ok: boolean | null } {
  switch (result) {
    case 'match': return { text: 'Passed', ok: true };
    case 'no_match': return { text: 'Failed: no match', ok: false };
    case 'not_found': return { text: 'Failed: not found', ok: false };
    case 'unavailable': return { text: 'Service unavailable: waiting. Do not use a copy.', ok: null };
    case 'pending': return { text: 'Checking', ok: null };
    default: return { text: 'Not started', ok: null };
  }
}

export function IdLine({ result, reference, at, channel }: { result?: string | null; reference?: string; at?: string | null; channel?: string }) {
  const s = idState(result);
  return (
    <div className="row" style={{ gap: 8, flexWrap: 'nowrap', alignItems: 'flex-start' }}>
      <span className={s.ok ? 'gate-mark' : 'gate-mark gate-no'} aria-hidden>{s.ok ? '✓' : s.ok === false ? '✕' : '…'}</span>
      <div>
        <div style={{ fontWeight: 700 }}>{s.text}</div>
        {reference || at ? <div className="mono muted" style={{ fontSize: 12 }}>National identity system{channel ? ` (${words(channel).toLowerCase()})` : ''}{reference ? `, ref ${reference}` : ''}{at ? `, ${dayTime(at)}` : ''}</div> : null}
      </div>
    </div>
  );
}

export function CaseParties({ c }: { c: CaseDetail }) {
  const list = useGet<Party[]>(`/v1/cases/${c.id}/parties`);
  const parties = list.data ?? [];
  const blocking = parties.filter((p) => p.status === 'active' && p.check?.result !== 'match');
  return (
    <Panel title="Parties and identity checks" actions={
      <ActionForm label="+ Add a party" path={`/v1/cases/${c.id}/parties`} fields={[
        { name: 'role', label: 'Role', type: 'select', required: true, options: ['seller', 'grantor', 'consenting_party', 'signatory'].map((r) => ({ value: r, label: words(r) })) },
        { name: 'name', label: 'Name on the deal documents', required: true },
        { name: 'organisation_name', label: 'Organisation (for a signatory)' },
        { name: 'id_number', label: 'National ID number', hint: 'Checked with the national identity system. Never upload a photo of the card.' },
        { name: 'adapter', label: 'How to check', type: 'select', initial: 'api', options: [{ value: 'api', label: 'Through the service' }, { value: 'staff_portal', label: 'Staff portal (record the result after)' }] },
      ]} body={(v) => ({ role: v.role, name: v.name, organisation_name: v.organisation_name || '', id_number: v.id_number || '', adapter: v.adapter || 'api' })} onDone={() => list.mutate()} submitLabel="Add party" />
    }>
      {blocking.length ? <div className="strip-ink"><span aria-hidden>🔒</span>Report cannot be released: {blocking.length === 1 ? `the ${words(blocking[0].role).toLowerCase()}'s identity check has not passed` : `${blocking.length} identity checks have not passed`}.</div> : null}
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton /> : parties.length ? (
        <div className="rows">
          {parties.map((p) => (
            <div key={p.id} className="rowlink" style={{ opacity: p.status === 'removed' ? 0.6 : 1 }}>
              <div className="main">
                <div className="label">{words(p.role)}{p.organisation_name ? ` for ${p.organisation_name}` : ''}</div>
                <div className="title">{p.name}</div>
                {p.status === 'removed' ? <div className="meta">Removed: {p.removed_reason}</div> : <IdLine result={p.check?.result} reference={p.check?.reference} at={p.check?.checked_at} channel={p.check?.channel} />}
              </div>
              {p.status === 'active' ? (
                <div className="row" style={{ gap: 6 }}>
                  {p.check?.result !== 'match' ? <ActionForm label={p.check ? 'Check again' : 'Run check'} path={`/v1/parties/${p.id}/checks`} fields={[
                    { name: 'id_number', label: 'National ID number', required: true },
                    { name: 'adapter', label: 'How to check', type: 'select', initial: 'api', options: [{ value: 'api', label: 'Through the service' }, { value: 'staff_portal', label: 'Staff portal' }] },
                  ]} onDone={() => list.mutate()} submitLabel="Check" intro="No photo or scan of the card, and no biometric data." /> : null}
                  <ActionForm label="Remove" path={`/v1/parties/${p.id}/removal`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={() => list.mutate()} submitLabel="Remove party" />
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : <Empty>No parties recorded. Add each seller, grantor, consenting party and signatory.</Empty>}
    </Panel>
  );
}
