import type { SectionSpec } from '../spec';

/** Records programme (SCR-BO-26): authorities that keep allocation records with Tenmina, their
 * allocations and overlaps, matches to cases, and revenue shares paid from Tenmina's own account. */
export const records: SectionSpec = {
  href: '/records',
  title: 'Records programme',
  screens: 'SCR-BO-26',
  intro: 'Stools, skins and families keep their allocation records with Tenmina under an agreement. Allocations are confirmed, matched to cases, and each authority is paid its share. A share is approved by an administrator who did not compute it.',
  resources: [
    {
      key: 'authorities', label: 'Authorities', list: '/v1/records/authorities',
      intro: 'Stools, skins and families who keep allocation records with Tenmina under an agreement, and their revenue share.',
      columns: [
        { key: 'name', label: 'Authority', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'region', label: 'Region', kind: 'text' },
        { key: 'share_per_case', label: 'Share per case', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      create: { label: 'Add an authority', path: '/v1/records/authorities', omit: ['agreement_evidence_id'], roles: ['AD'] },
      actions: [{ label: 'Add representative', path: '/v1/records/authorities/{id}/representatives', fields: [{ name: 'authorisation_evidence_id', type: 'file', upload: { subject_type: 'rec_authority' } }] }],
    },
    {
      key: 'allocations', label: 'Allocations', list: '/v1/records/allocations',
      intro: 'Each allocation an authority recorded. Confirm it once checked; overlaps with other allocations show on the allocation.',
      columns: [
        { key: 'authority_name', label: 'Authority', kind: 'name' },
        { key: 'allottee_name', label: 'Allottee', kind: 'text' },
        { key: 'allocated_on', label: 'Allocated', kind: 'date' },
        { key: 'area_sqm', label: 'Area m²', kind: 'mono' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'q'],
      title: (r) => `${r.allottee_name} · ${r.reference}`,
      actions: [
        { label: 'Confirm', path: '/v1/records/allocations/{id}/confirm', tone: 'primary', when: (r) => r.status === 'captured' },
        { label: 'Correct', path: '/v1/records/allocations/{id}/corrections', tone: 'ghost' },
        { label: 'Mark disputed', path: '/v1/records/allocations/{id}/dispute', tone: 'ghost', when: (r) => r.status !== 'disputed' },
      ],
      subs: [{ label: 'Overlaps', from: 'overlaps', actions: [{ label: 'Resolve', path: '/v1/records/overlaps/{id}/resolutions' }] }],
    },
    {
      key: 'matches', label: 'Matches', list: '/v1/records/matches',
      intro: 'A case plot matched against the allocation records. A case manager confirms or rejects each match.',
      columns: [
        { key: 'case_reference', label: 'Case', kind: 'ref' },
        { key: 'authority_name', label: 'Authority', kind: 'name' },
        { key: 'kind', label: 'Match', kind: 'text' },
        { key: 'share_of_plot', label: 'Share of plot', kind: 'mono' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      create: { label: 'Match a case', path: '/v1/records/matches/run', showResult: true },
      actions: [
        { label: 'Confirm match', path: '/v1/records/matches/{id}/confirm', tone: 'primary', when: (r) => ['proposed', 'review'].includes(r.status) },
        { label: 'Reject match', path: '/v1/records/matches/{id}/reject', tone: 'ghost', when: (r) => ['proposed', 'review'].includes(r.status) },
      ],
    },
    {
      key: 'shares', label: 'Revenue shares', list: '/v1/records/revenue-shares', roles: ['AD'],
      intro: 'Paid by Tenmina from its own account, never from client money. Amounts are working assumptions [TO VERIFY].',
      columns: [
        { key: 'authority_name', label: 'Authority', kind: 'name' },
        { key: 'period_start', label: 'From', kind: 'date' },
        { key: 'period_end', label: 'To', kind: 'date' },
        { key: 'case_count', label: 'Cases', kind: 'mono' },
        { key: 'amount', label: 'Amount', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      create: { label: 'Compute shares', path: '/v1/records/revenue-shares/compute', showResult: true },
      actions: [
        { label: 'Approve', path: '/v1/records/revenue-shares/{id}/approve', tone: 'primary', mfa: true, when: (r) => r.status === 'computed', confirm: 'Paid by Tenmina from its own account. You did not compute this share.' },
        { label: 'Mark paid', path: '/v1/records/revenue-shares/{id}/paid', when: (r) => r.status === 'approved' },
      ],
    },
  ],
};
