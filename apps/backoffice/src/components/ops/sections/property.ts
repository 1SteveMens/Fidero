import type { SectionSpec } from '../spec';

const inspectorSource = { path: '/v1/licences', query: { role: 'IN', status: 'verified' }, value: 'person', label: (l: Record<string, unknown>) => `${String(l.number)} · ${String(l.body)}` };

export const property: SectionSpec = {
  href: '/property',
  title: 'Property management',
  screens: 'SCR-BO-31',
  intro: 'Rent goes to the owner\'s own account at the partner bank, never through Tenmina. Rent is matched from the bank\'s statement lines under the owner\'s written mandate. Repairs are paid only after an inspection with photos.',
  resources: [
    {
      key: 'properties', label: 'Managed properties', list: '/v1/managed-properties', subject: 'managed_property',
      columns: [
        { key: 'title', label: 'Property', kind: 'name' },
        { key: 'locality', label: 'Where', kind: 'text' },
        { key: 'owner', label: 'Owner', kind: 'name' },
        { key: 'next_inspection_due_on', label: 'Next inspection', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      hide: ['row_version'],
      links: { mandate: 'mandate', onboarding_inspection: 'inspections', active_tenancy: 'tenancies', onboarding_case: '/cases' },
      actions: [
        { label: 'Record the mandate', path: '/v1/managed-properties/{id}/statement-mandates', tone: 'primary', when: (r) => !r.mandate, confirm: 'The owner\'s written mandate lets the bank share statement lines for the rent account only.' },
        { label: 'Set the rent account', path: '/v1/managed-properties/{id}/rent-account', method: 'PUT', when: (r) => !r.rent_account, fields: [{ name: 'bank_account_id', label: 'Owner\'s own account at the partner bank', source: { path: '/v1/bank-accounts', query: { status: 'verified' }, label: (b) => `${b.account_name ?? b.holder_name ?? 'Account'} · ending ${b.account_last4 ?? b.last4 ?? ''}` } }] },
        { label: 'Record a tenancy', path: '/v1/managed-properties/{id}/tenancies', when: (r) => !r.active_tenancy && r.status !== 'ended', fields: [{ name: 'agreement_evidence_id', type: 'file', label: 'Tenancy agreement' }] },
        { label: 'Import rent statement', path: '/v1/managed-properties/{id}/rent-statements', when: (r) => !!r.mandate, fields: [{ name: 'content', type: 'textfile', label: 'Statement file from the bank', fileNameField: 'original_name' }, { name: 'original_name', type: 'hidden' }] },
        { label: 'Schedule an inspection', path: '/v1/managed-properties/{id}/inspections', tone: 'ghost', fields: [{ name: 'inspector_id', label: 'Inspector', source: inspectorSource }] },
        { label: 'Pause', path: '/v1/managed-properties/{id}/pause', tone: 'ghost', when: (r) => r.status === 'managed' },
        { label: 'Resume', path: '/v1/managed-properties/{id}/resume', when: (r) => r.status === 'paused' },
        { label: 'End management', path: '/v1/managed-properties/{id}/end', tone: 'ghost', when: (r) => r.status !== 'ended' },
      ],
      subs: [
        {
          label: 'Rent periods', path: '/v1/managed-properties/{id}/rent-periods', note: 'A manual match needs a second staff check.',
          columns: [{ key: 'due_on', label: 'Due', kind: 'date' }, { key: 'amount_due', label: 'Due', kind: 'money' }, { key: 'amount_received', label: 'Received', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }],
          actions: [
            { label: 'Match a line', path: '/v1/rent-periods/{id}/manual-matches', when: (p) => ['due', 'late', 'partial'].includes(p.status), fields: [{ name: 'statement_line_id', label: 'Unmatched statement line', source: { path: '/v1/managed-properties/{parent}/unmatched-lines', label: (l) => `${l.value_date ?? l.date ?? ''} · ${l.amount?.amount ?? l.amount ?? ''} · ${l.narrative ?? l.description ?? ''}` } }] },
            { label: 'Check match', path: '/v1/rent-periods/{id}/manual-match-checks', tone: 'primary', when: (p) => !!p.manual_match_pending || !!p.pending_manual_match, fields: [{ name: 'agree', default: true }] },
            { label: 'Write off', path: '/v1/rent-periods/{id}/write-offs', tone: 'ghost', when: (p) => ['late', 'partial'].includes(p.status) },
          ],
        },
        { label: 'Unmatched statement lines', path: '/v1/managed-properties/{id}/unmatched-lines' },
        { label: 'Inspections', path: '/v1/managed-properties/{id}/inspections', link: 'inspections', columns: [{ key: 'kind', label: 'Kind', kind: 'text' }, { key: 'scheduled_for', label: 'Date', kind: 'date' }, { key: 'outcome', label: 'Outcome', kind: 'text' }, { key: 'status', label: 'Status', kind: 'status' }] },
        { label: 'Timeline', path: '/v1/managed-properties/{id}/timeline' },
      ],
    },
    {
      key: 'mandate', label: 'Mandate', list: '/v1/managed-properties', detail: '/v1/statement-mandates/{id}', hidden: true, columns: [],
      actions: [
        { label: 'Record bank acknowledgement', path: '/v1/statement-mandates/{id}/acknowledgements', tone: 'primary', fields: [{ name: 'evidence_id', type: 'file', upload: { subject_type: 'managed_property', subjectId: (r) => String(r.property ?? r.property_id) } }] },
        { label: 'Revoke', path: '/v1/statement-mandates/{id}/revocations', tone: 'ghost' },
      ],
    },
    {
      key: 'tenancies', label: 'Tenancies', list: '/v1/tenancies', subject: 'tenancy',
      columns: [
        { key: 'property_title', label: 'Property', kind: 'name' },
        { key: 'tenant', label: 'Tenant', kind: 'name' },
        { key: 'rent', label: 'Rent', kind: 'money' },
        { key: 'period', label: 'Every', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [{ label: 'End tenancy', path: '/v1/tenancies/{id}/end', tone: 'ghost', when: (r) => r.status === 'active' }],
    },
    {
      key: 'repairs', label: 'Repairs and quotes', list: '/v1/repairs', subject: 'repair',
      intro: 'At least two quotes from vetted contractors, unless a reviewer records an exception. The owner approves one. Money is released only after an inspection with photos.',
      columns: [
        { key: 'property_title', label: 'Property', kind: 'name' },
        { key: 'title', label: 'Repair', kind: 'text' },
        { key: 'quotes', label: 'Quotes', kind: 'count' },
        { key: 'urgent', label: 'Urgent', kind: 'bool' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      hide: ['quotes', 'row_version'],
      actions: [
        { label: 'Add a quote', path: '/v1/repairs/{id}/quotes', tone: 'primary', when: (r) => ['reported', 'quoting', 'quotes_ready'].includes(r.status), fields: [
          { name: 'contractor_id', label: 'Vetted contractor', source: { path: '/v1/panel-members', query: { kind: 'contractor', status: 'active' }, label: (c) => c.name } },
          { name: 'payee_id', label: 'Contractor\'s verified account', source: { path: '/v1/payees', query: { status: 'verified' }, label: (p) => `${p.legal_name} · ending ${p.account_last4}` } },
          { name: 'evidence_id', type: 'file', label: 'Quote document' },
        ] },
        { label: 'Single-quote exception', path: '/v1/repairs/{id}/single-quote-exceptions', roles: ['RV'], tone: 'ghost', when: (r) => ['quoting', 'reported'].includes(r.status) },
        { label: 'Schedule inspection', path: '/v1/repairs/{id}/inspections', when: (r) => ['in_progress', 'funded'].includes(r.status) || !!r.work_done_at, fields: [{ name: 'inspector_id', label: 'Inspector', source: inspectorSource }] },
        { label: 'Prepare release to contractor', path: '/v1/repairs/{id}/instructions', when: (r) => r.status === 'inspected', confirm: 'Only after a pass. Names the contractor\'s verified account. Two staff approve it in Approvals.' },
        { label: 'Close', path: '/v1/repairs/{id}/close', tone: 'ghost', when: (r) => !['paid', 'cancelled', 'rejected'].includes(r.status) },
      ],
      subs: [{
        label: 'Quotes', from: 'quotes',
        columns: [{ key: 'contractor_name', label: 'Contractor', kind: 'name' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'valid_until', label: 'Valid until', kind: 'date' }, { key: 'status', label: 'Status', kind: 'status' }],
        actions: [{ label: 'Withdraw', path: '/v1/repair-quotes/{id}/withdraw', tone: 'ghost', when: (q) => q.status !== 'withdrawn' }],
      }],
    },
    {
      key: 'inspections', label: 'Inspections', list: '/v1/pmg-inspections', subject: 'property_inspection',
      columns: [
        { key: 'property_title', label: 'Property', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'scheduled_for', label: 'Date', kind: 'date' },
        { key: 'outcome', label: 'Outcome', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      create: { label: 'Run the inspection schedule', path: '/v1/pmg-jobs/inspection-schedule', tone: 'ghost', confirm: 'Creates inspections that are due by each property\'s interval.', showResult: true },
      actions: [
        { label: 'Assign inspector', path: '/v1/pmg-inspections/{id}/assignments', tone: 'primary', when: (r) => ['scheduled', 'assigned'].includes(r.status), fields: [{ name: 'inspector_id', label: 'Inspector', source: inspectorSource }] },
        { label: 'Cancel', path: '/v1/pmg-inspections/{id}/cancel', tone: 'ghost', when: (r) => ['scheduled', 'assigned'].includes(r.status) },
      ],
    },
  ],
};
