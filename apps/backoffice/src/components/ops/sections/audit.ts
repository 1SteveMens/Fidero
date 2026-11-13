import type { SectionSpec } from '../spec';

export const audit: SectionSpec = {
  href: '/audit',
  title: 'Audit log',
  screens: 'SCR-BO-22',
  intro: 'Every action, append-only and hash-chained. Search it, follow one record\'s trail, and check the chain has not been changed.',
  resources: [
    {
      key: 'events', label: 'Search', list: '/v1/audit-events', detail: null, idKey: 'seq',
      filters: ['action', 'entity', 'entity_id', 'actor_id', 'case_id', 'occurred_from', 'occurred_to'],
      columns: [
        { key: 'seq', label: 'Seq', kind: 'mono' },
        { key: 'occurred_at', label: 'When', kind: 'when' },
        { key: 'actor', label: 'Who', kind: 'name' },
        { key: 'action', label: 'Action', kind: 'mono' },
        { key: 'entity', label: 'Record', render: (r) => `${r.entity} ${String(r.entity_id ?? '').slice(0, 8)}` },
      ],
      rowActions: [],
    },
    {
      key: 'chain', label: 'Chain checks', list: '/v1/audit-chain-checks', detail: null,
      intro: 'A check walks the whole chain and compares it with the anchors written outside the database.',
      columns: [
        { key: 'ran_at', label: 'Ran', kind: 'when' },
        { key: 'ok', label: 'Chain intact', kind: 'bool' },
        { key: 'checked', label: 'Entries', kind: 'mono' },
        { key: 'anchors_ok', label: 'Anchors match', kind: 'bool' },
        { key: 'broken_at', label: 'Broken at', kind: 'mono' },
      ],
      create: { label: 'Verify the chain now', path: '/v1/audit-events/verify', tone: 'primary', showResult: true },
    },
    {
      key: 'anchors', label: 'Anchors', list: '/v1/audit-anchors', detail: null,
      columns: [
        { key: 'seq', label: 'Up to', kind: 'mono' },
        { key: 'hash', label: 'Hash', kind: 'mono' },
        { key: 'anchored_at', label: 'Anchored', kind: 'when' },
        { key: 'location', label: 'Where', kind: 'mono' },
      ],
      create: { label: 'Write an anchor now', path: '/v1/audit-anchors/new', tone: 'ghost', roles: ['AD'], showResult: true },
    },
    {
      key: 'integrity', label: 'Evidence integrity', list: '/v1/integrity-incidents', roles: ['RV', 'AD'],
      intro: 'Random re-hashing of stored evidence. A mismatch opens an incident.',
      columns: [
        { key: 'created_at', label: 'Found', kind: 'when' },
        { key: 'evidence', label: 'Evidence', kind: 'mono' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      create: { label: 'Run an integrity sample', path: '/v1/integrity-runs', tone: 'ghost', showResult: true },
      actions: [{ label: 'Resolve', path: '/v1/integrity-incidents/{id}/resolve', tone: 'primary', when: (r) => r.status === 'open' }],
    },
  ],
};
