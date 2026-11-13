import type { SectionSpec } from '../spec';

export const insurance: SectionSpec = {
  href: '/insurance',
  title: 'Insurance',
  screens: 'EP-INS',
  intro: 'Cover is the licensed insurer\'s product, never Tenmina\'s. Premiums go to the insurer\'s verified account only. Only the insurer decides applications and claims: staff see them, they do not decide them.',
  resources: [
    {
      key: 'insurers', label: 'Insurers', list: '/v1/insurance/insurers',
      columns: [
        { key: 'name', label: 'Insurer', kind: 'name' },
        { key: 'licence_number', label: 'Licence', kind: 'mono' },
        { key: 'licence_valid_until', label: 'Valid until', kind: 'date' },
        { key: 'payee', label: 'Payee', kind: 'name' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      create: { label: 'Add an insurer partner', path: '/v1/insurance/insurers', roles: ['AD'], fields: [
        { name: 'partner_id', label: 'Partner record', source: { path: '/v1/admin/partners', query: { kind: 'insurer' }, label: (p) => p.name } },
        { name: 'payee_id', label: 'Insurer\'s verified account', source: { path: '/v1/payees', query: { status: 'verified' }, label: (p) => `${p.legal_name} · ending ${p.account_last4}` } },
      ], omit: ['licence_evidence_id'] },
      actions: [{ label: 'Edit licence and status', path: '/v1/insurance/insurers/{id}', method: 'PATCH', roles: ['AD'], tone: 'ghost', omit: ['licence_evidence_id'] }],
    },
    {
      key: 'licences', label: 'Our intermediary licence', list: '/v1/insurance/intermediary-licences', detail: null, roles: ['AD'],
      intro: 'Without a valid intermediary licence for the country, the cover line is not shown to clients.',
      columns: [
        { key: 'body', label: 'Body', kind: 'name' },
        { key: 'reference', label: 'Reference', kind: 'mono' },
        { key: 'valid_until', label: 'Valid until', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      create: { label: 'Record a licence', path: '/v1/insurance/intermediary-licences', roles: ['AD'], omit: ['evidence_id'] },
    },
    {
      key: 'products', label: 'Products', list: '/v1/insurance/products',
      intro: 'Each product shows the insurer\'s name, its terms and the statement that Tenmina is not the insurer.',
      columns: [
        { key: 'name', label: 'Product', kind: 'name' },
        { key: 'insurer_name', label: 'Insurer', kind: 'text' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'premium', label: 'Premium', kind: 'money' },
        { key: 'premium_period', label: 'Per', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      create: { label: 'Add a product', path: '/v1/insurance/products', roles: ['AD'], omit: ['evidence_id'], fields: [{ name: 'insurer_id', label: 'Insurer', source: { path: '/v1/insurance/insurers', label: (i) => i.name } }] },
      actions: [
        { label: 'Publish', path: '/v1/insurance/products/{id}/publication', tone: 'primary', roles: ['AD'], when: (r) => r.status === 'draft', confirm: 'Clients in this country will see the product, with the insurer\'s name and terms.' },
        { label: 'Withdraw', path: '/v1/insurance/products/{id}/withdrawal', tone: 'ghost', roles: ['AD'], when: (r) => r.status === 'published' },
      ],
    },
    {
      key: 'applications', label: 'Applications', list: '/v1/insurance/applications',
      intro: 'Sent to the insurer in the agreed format. The insurer accepts or declines.',
      columns: [
        { key: 'product_name', label: 'Product', kind: 'name' },
        { key: 'insurer_name', label: 'Insurer', kind: 'text' },
        { key: 'insurer_reference', label: 'Insurer ref', kind: 'mono' },
        { key: 'submitted_to_insurer_at', label: 'Sent', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
    },
    {
      key: 'policies', label: 'Policies', list: '/v1/insurance/policies',
      columns: [
        { key: 'policy_number', label: 'Policy', kind: 'ref' },
        { key: 'product_name', label: 'Product', kind: 'name' },
        { key: 'insurer_name', label: 'Insurer', kind: 'text' },
        { key: 'renews_on', label: 'Renews', kind: 'date' },
        { key: 'premium', label: 'Premium', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => r.policy_number,
    },
    {
      key: 'premiums', label: 'Premiums', list: '/v1/insurance/premiums', subject: 'ins_premium',
      intro: 'Paid by the client straight to the insurer, or by the bank from money held for it. The payee is always the insurer\'s verified account.',
      columns: [
        { key: 'policy_number', label: 'Policy', kind: 'ref' },
        { key: 'insurer_name', label: 'Insurer', kind: 'text' },
        { key: 'due_on', label: 'Due', kind: 'date' },
        { key: 'amount', label: 'Amount', kind: 'money' },
        { key: 'route', label: 'Route', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Prepare instruction to the insurer', path: '/v1/insurance/premiums/{id}/instructions', when: (r) => r.route === 'held_funds_to_insurer' && ['due', 'overdue'].includes(r.status), confirm: 'The instruction names the insurer\'s verified account. Two staff approve it in Approvals.' },
        { label: 'Insurer confirms receipt', path: '/v1/insurance/premiums/{id}/insurer-confirmation', tone: 'primary', when: (r) => ['client_reported', 'instructed', 'due', 'overdue'].includes(r.status), fields: [{ name: 'received', default: true }, { name: 'evidence_id', type: 'file', label: 'Insurer receipt' }] },
      ],
    },
    {
      key: 'claims', label: 'Claims', list: '/v1/insurance/claims',
      intro: 'Read only. The insurer decides every claim; no Tenmina user can enter a decision.',
      columns: [
        { key: 'insurer_reference', label: 'Claim', kind: 'ref' },
        { key: 'description', label: 'What happened', kind: 'text' },
        { key: 'event_date', label: 'Date', kind: 'date' },
        { key: 'insurer_status', label: 'Insurer says', kind: 'status' },
      ],
      title: (r) => `Claim ${r.insurer_reference ?? ''}`,
    },
  ],
};
