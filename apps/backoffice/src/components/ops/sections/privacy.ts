import type { SectionSpec } from '../spec';

export const privacy: SectionSpec = {
  href: '/privacy',
  title: 'Data protection',
  screens: 'SCR-BO-24',
  intro: 'Access, correction and erasure requests within their deadlines. Legal holds and bulk exports need two approvals. Retention runs on the rules below; what banking law keeps is kept and the person is told why.',
  resources: [
    {
      key: 'requests', roles: ['AD', 'DPO'], label: 'Requests', list: '/v1/dpr/requests',
      columns: [
        { key: 'subject', label: 'Person', kind: 'name' },
        { key: 'type', label: 'Type', kind: 'text' },
        { key: 'due_on', label: 'Due', kind: 'date' },
        { key: 'overdue', label: 'Overdue', kind: 'bool' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => `${String(r.type)} request · ${r.subject?.full_name ?? ''}`,
      create: { label: 'Log a request', path: '/v1/dpr/requests', fields: [{ name: 'subject', hint: 'The person\'s ID (Clients and orders › People).' }] },
      actions: [
        { label: 'Produce the export', path: '/v1/dpr/requests/{id}/export', tone: 'primary', when: (r) => r.type === 'access' && ['open', 'in_progress'].includes(r.status) },
        { label: 'Apply a correction', path: '/v1/dpr/requests/{id}/corrections', tone: 'primary', when: (r) => r.type === 'correction' && ['open', 'in_progress'].includes(r.status) },
        { label: 'Erase', path: '/v1/dpr/requests/{id}/erase', tone: 'danger', hold: true, when: (r) => r.type === 'erasure' && ['open', 'in_progress', 'waiting'].includes(r.status), confirm: 'Personal data is anonymised. What the law keeps is kept and listed for the person. Open matters block erasure.' },
        { label: 'Complete', path: '/v1/dpr/requests/{id}/complete', when: (r) => ['open', 'in_progress', 'waiting'].includes(r.status) },
        { label: 'Reject', path: '/v1/dpr/requests/{id}/reject', tone: 'ghost', when: (r) => ['open', 'in_progress', 'waiting'].includes(r.status) },
      ],
    },
    {
      key: 'holds', roles: ['LW', 'AD', 'DPO', 'RV'], label: 'Legal holds', list: '/v1/dpr/legal-holds',
      intro: 'Stops retention deleting a record. Lifting a hold needs two approvals.',
      columns: [
        { key: 'subject_type', label: 'On', kind: 'name' },
        { key: 'reason', label: 'Reason', kind: 'text' },
        { key: 'placed_at', label: 'Placed', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => `Hold on ${r.subject_type}`,
      create: { label: 'Place a hold', path: '/v1/dpr/legal-holds' },
      actions: [
        { label: 'Ask to lift', path: '/v1/dpr/legal-holds/{id}/lift-requests', tone: 'ghost', when: (r) => r.status === 'active' },
        { label: 'Approve lift', path: '/v1/dpr/legal-holds/{id}/approvals', tone: 'primary', mfa: true, fixed: { decision: 'approve' }, only: ['note'], when: (r) => r.status === 'lift_pending' },
        { label: 'Reject lift', path: '/v1/dpr/legal-holds/{id}/approvals', tone: 'ghost', mfa: true, fixed: { decision: 'reject' }, only: ['note'], when: (r) => r.status === 'lift_pending' },
      ],
    },
    {
      key: 'exports', roles: ['AD', 'DPO'], label: 'Bulk exports', list: '/v1/dpr/bulk-exports',
      intro: 'Personal data leaves Tenmina in bulk only with a purpose and two approvals. Each download is logged.',
      columns: [
        { key: 'purpose', label: 'Purpose', kind: 'name' },
        { key: 'row_count', label: 'Rows', kind: 'mono' },
        { key: 'link_expires_at', label: 'Link expires', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => r.purpose,
      create: { label: 'Ask for an export', path: '/v1/dpr/bulk-exports' },
      actions: [
        { label: 'Approve export', path: '/v1/dpr/bulk-exports/{id}/approvals', tone: 'primary', mfa: true, fixed: { decision: 'approve' }, only: ['note'], when: (r) => r.status === 'pending_approval', confirm: 'You did not ask for this export. Two approvals are needed.' },
        { label: 'Reject export', path: '/v1/dpr/bulk-exports/{id}/approvals', tone: 'ghost', mfa: true, fixed: { decision: 'reject' }, only: ['note'], when: (r) => r.status === 'pending_approval' },
        { label: 'Download', path: '/v1/dpr/bulk-exports/{id}/download', method: 'GET', download: 'export.csv', when: (r) => r.status === 'produced' },
      ],
    },
    {
      key: 'retention', roles: ['AD', 'DPO'], label: 'Retention rules', list: '/v1/dpr/retention-rules',
      columns: [
        { key: 'data_class', label: 'Data', kind: 'name' },
        { key: 'period_label', label: 'Kept for', kind: 'text' },
        { key: 'anchor', label: 'From', kind: 'text' },
        { key: 'action', label: 'Then', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => String(r.data_class).replace(/_/g, ' '),
      create: { label: 'Add a rule', path: '/v1/dpr/retention-rules', roles: ['AD', 'DPO'] },
      actions: [{ label: 'Change rule', path: '/v1/dpr/retention-rules/{id}', method: 'PATCH', roles: ['AD', 'DPO'], tone: 'ghost' }],
    },
    {
      key: 'runs', roles: ['AD', 'DPO'], label: 'Retention runs', list: '/v1/dpr/retention-runs',
      columns: [{ key: 'created_at', label: 'Run', kind: 'when' }, { key: 'status', label: 'Status', kind: 'status' }],
      create: { label: 'Run retention now', path: '/v1/dpr/retention-runs', roles: ['AD', 'DPO'], confirm: 'Anonymises or deletes what has passed its period, except anything on legal hold.', showResult: true },
    },
    {
      key: 'catalogue', roles: ['AD', 'DPO'], label: 'Data catalogue', list: '/v1/dpr/data-catalogue', detail: null,
      columns: [
        { key: 'table_name', label: 'Table', kind: 'mono' },
        { key: 'field_name', label: 'Field', kind: 'mono' },
        { key: 'data_class', label: 'Class', kind: 'text' },
        { key: 'personal', label: 'Personal', kind: 'bool' },
        { key: 'special_category', label: 'Special', kind: 'bool' },
      ],
      create: { label: 'Sync from the schema', path: '/v1/dpr/data-catalogue/sync', tone: 'ghost', roles: ['AD', 'DPO'], showResult: true },
      rowActions: [{ label: 'Edit', path: '/v1/dpr/data-catalogue/{id}', method: 'PATCH', tone: 'ghost', roles: ['AD', 'DPO'] }],
    },
    {
      key: 'locations', roles: ['AD', 'DPO'], label: 'Data locations', list: '/v1/dpr/data-locations', detail: null,
      columns: [
        { key: 'service', label: 'Service', kind: 'name' },
        { key: 'vendor', label: 'Vendor', kind: 'text' },
        { key: 'region', label: 'Region', kind: 'text' },
        { key: 'transfer_basis', label: 'Basis', kind: 'text' },
      ],
      create: { label: 'Add a location', path: '/v1/dpr/data-locations', roles: ['AD', 'DPO'] },
      rowActions: [{ label: 'Edit', path: '/v1/dpr/data-locations/{id}', method: 'PATCH', tone: 'ghost', roles: ['AD', 'DPO'] }],
    },
    {
      key: 'notices', roles: ['AD', 'DPO'], label: 'Privacy notices', list: '/v1/dpr/privacy-notices', detail: null,
      columns: [
        { key: 'version', label: 'Version', kind: 'mono' },
        { key: 'title', label: 'Title', kind: 'name' },
        { key: 'published_at', label: 'Published', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      create: { label: 'New notice version', path: '/v1/dpr/privacy-notices', roles: ['AD', 'DPO'] },
    },
    {
      key: 'consents', roles: ['AD', 'DPO'], label: 'Consents', list: '/v1/consents', detail: null,
      columns: [
        { key: 'purpose', label: 'Purpose', kind: 'name' },
        { key: 'text_version', label: 'Text', kind: 'mono' },
        { key: 'given_at', label: 'Given', kind: 'when' },
        { key: 'withdrawn_at', label: 'Withdrawn', kind: 'when' },
      ],
    },
  ],
};
