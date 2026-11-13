import type { SectionSpec } from '../spec';

export const clients: SectionSpec = {
  href: '/clients',
  title: 'Clients and orders',
  screens: 'EP-ACC · EP-ORD',
  intro: 'Find a person, see what they ordered, their family members, bank accounts and identity checks. Staff see only the countries they work in.',
  resources: [
    {
      key: 'orders', label: 'Orders', list: '/v1/orders',
      columns: [
        { key: 'reference', label: 'Order', kind: 'ref' },
        { key: 'client_name', label: 'Client', kind: 'name' },
        { key: 'product_name', label: 'Service', kind: 'text' },
        { key: 'price', label: 'Price', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'kind'],
      links: { client: 'people' },
      actions: [
        { label: 'Cancel order', path: '/v1/orders/{id}/cancel', tone: 'ghost', when: (r) => ['draft', 'awaiting_payment'].includes(r.status) },
      ],
      subs: [
        { label: 'Family members', path: '/v1/family-members', query: (p) => ({ client: p.client }), link: (r) => `/fees/family/${r.id}`, columns: [{ key: 'full_name', label: 'Name', kind: 'name' }, { key: 'relationship', label: 'Relationship', kind: 'text' }, { key: 'phone', label: 'Phone', kind: 'mono' }, { key: 'status', label: 'Status', kind: 'status' }], note: 'Open one for the statement of bills, payments and receipts.' },
        { label: 'Payments', path: '/v1/orders/{id}/payments', link: (r) => `/payments/payments/${r.id}`, columns: [{ key: 'method', label: 'Method', kind: 'text' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }] },
        { label: 'Documents', path: '/v1/orders/{id}/documents' },
        { label: 'Terms accepted', path: '/v1/orders/{id}/acceptances' },
      ],
    },
    {
      key: 'people', label: 'People', list: '/v1/admin/people', roles: ['AD'],
      intro: 'Search by name, email or phone. Escrows, cases and representatives are linked from each person.',
      columns: [
        { key: 'full_name', label: 'Name', kind: 'name' },
        { key: 'email', label: 'Email', kind: 'mono' },
        { key: 'home_country', label: 'Country', kind: 'mono' },
        { key: 'id_check_status', label: 'Identity', kind: 'status' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['q', 'role'],
      title: (r) => r.full_name,
      subs: [
        { label: 'Role grants', from: 'grants', actions: [{ label: 'Revoke', path: '/v1/admin/role-grants/{id}/revoke', tone: 'ghost', mfa: true, roles: ['AD'] }] },
        { label: 'Family members', path: '/v1/family-members', query: (p) => ({ client: p.id }), link: (r) => `/fees/family/${r.id}`, columns: [{ key: 'full_name', label: 'Name', kind: 'name' }, { key: 'relationship', label: 'Relationship', kind: 'text' }, { key: 'status', label: 'Status', kind: 'status' }] },
        { label: 'Orders', path: '/v1/orders', query: (p) => ({ client: p.id }), link: 'orders', columns: [{ key: 'reference', label: 'Order', kind: 'ref' }, { key: 'product_name', label: 'Service', kind: 'text' }, { key: 'status', label: 'Status', kind: 'status' }] },
        { label: 'Cases', path: '/v1/cases', query: (p) => ({ client: p.id }), link: (r) => `/cases/${r.id}` },
        { label: 'Escrows', path: '/v1/escrows', query: (p) => ({ client: p.id }), link: (r) => `/escrow/${r.id}` },
      ],
    },
    {
      key: 'identity', label: 'Identity checks', list: '/v1/identity-checks', roles: ['CM', 'RV'],
      intro: 'A provider result that is unclear comes here for a manual decision.',
      columns: [
        { key: 'person', label: 'Person', kind: 'name' },
        { key: 'document_type', label: 'Document', kind: 'text' },
        { key: 'provider_result', label: 'Provider', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
        { key: 'created_at', label: 'When', kind: 'when' },
      ],
      filters: ['status'],
      title: (r) => `Identity check · ${r.person?.full_name ?? ''}`,
      actions: [{ label: 'Decide manually', path: '/v1/identity-checks/{id}/manual-decision', tone: 'primary', when: (r) => r.status === 'manual_review', omit: ['person'], fields: [{ name: 'evidence', type: 'file', upload: { subject_type: 'person', subjectId: (r) => String(r.person?.id) } }] }],
    },
    {
      key: 'national-id', label: 'National ID checks', list: '/v1/national-id-checks', roles: ['CM', 'RV'], screen: 'SCR-BO-44',
      intro: 'One line per seller, grantor, consenting party and payee. Never a photo or scan of the card.',
      columns: [
        { key: 'subject_name', label: 'Who', kind: 'name' },
        { key: 'subject_role', label: 'As', kind: 'text' },
        { key: 'channel', label: 'Channel', kind: 'text' },
        { key: 'result', label: 'Result', kind: 'status' },
        { key: 'checked_at', label: 'Checked', kind: 'when' },
      ],
      create: { label: 'Run a check', path: '/v1/national-id-checks' },
      actions: [
        { label: 'Retry', path: '/v1/national-id-checks/{id}/retry', when: (r) => !r.result || r.result === 'service_unavailable' },
        { label: 'Record staff-portal result', path: '/v1/national-id-checks/{id}/staff-result', tone: 'primary', when: (r) => !r.result || r.adapter === 'staff_portal' },
      ],
    },
    {
      key: 'bank-accounts', label: 'Bank accounts', list: '/v1/bank-accounts', roles: ['CM', 'RV', 'AD'],
      intro: 'Client source accounts for refunds and owners\' rent accounts. A second person checks each one.',
      columns: [
        { key: 'account_name', label: 'Account name', kind: 'name' },
        { key: 'bank_name', label: 'Bank', kind: 'text' },
        { key: 'account_last4', label: 'Ending', kind: 'mono' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Record verification', path: '/v1/bank-accounts/{id}/verifications', tone: 'primary', when: (r) => r.status === 'pending' || r.status === 'unverified', fields: [{ name: 'evidence', type: 'file', upload: { subject_type: 'bank_account' } }] },
        { label: 'Approve account', path: '/v1/bank-accounts/{id}/approvals', mfa: true, fixed: { decision: 'approve' }, only: ['note'], when: (r) => r.status === 'pending_approval' },
        { label: 'Suspend', path: '/v1/bank-accounts/{id}/suspend', tone: 'ghost', when: (r) => r.status === 'verified' },
      ],
    },
    {
      key: 'referral-codes', label: 'Referral codes', list: '/v1/referral-codes', detail: null,
      columns: [
        { key: 'code', label: 'Code', kind: 'mono' },
        { key: 'owner_label', label: 'Owner', kind: 'name' },
        { key: 'discount_pct', label: 'Discount %', kind: 'mono' },
        { key: 'reward', label: 'Reward', kind: 'money' },
        { key: 'uses', label: 'Uses', kind: 'mono' },
        { key: 'active', label: 'Active', kind: 'bool' },
      ],
      create: { label: 'New referral code', path: '/v1/referral-codes', roles: ['AD'], omit: ['owner'] },
      rowActions: [{ label: 'Deactivate', path: '/v1/referral-codes/{id}/deactivate', tone: 'ghost', roles: ['AD'], when: (r) => r.active }],
    },
    {
      key: 'rewards', label: 'Referral rewards', list: '/v1/referral-rewards', detail: null,
      intro: 'Paid by Tenmina from its own account, never from client money.',
      columns: [
        { key: 'code', label: 'Code', kind: 'mono' },
        { key: 'order_reference', label: 'Order', kind: 'ref' },
        { key: 'reward', label: 'Reward', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      rowActions: [
        { label: 'Mark paid', path: '/v1/referral-rewards/{id}/paid', roles: ['AD', 'RV'], when: (r) => r.status === 'owed' },
        { label: 'Void', path: '/v1/referral-rewards/{id}/void', tone: 'ghost', roles: ['AD', 'RV'], when: (r) => r.status === 'owed' },
      ],
    },
  ],
};
