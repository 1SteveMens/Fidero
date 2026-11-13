import type { SectionSpec } from '../spec';


export const fees: SectionSpec = {
  href: '/fees',
  title: 'Family payments',
  screens: 'SCR-BO-27 · SCR-BO-30',
  intro: 'Institutions are checked before any bill is paid. Bills are checked with the named contact. The bank pays the institution, or the client pays it directly and the institution confirms. Never cash to a relative.',
  resources: [
    {
      key: 'institutions', label: 'Institutions', list: '/v1/institutions', screen: 'SCR-BO-27', subject: 'institution',
      intro: 'Registration, a bank account in the institution\'s own name and a named contact. A second person checks the account.',
      columns: [
        { key: 'legal_name', label: 'Institution', kind: 'name' },
        { key: 'type', label: 'Type', kind: 'text' },
        { key: 'registration_number', label: 'Registration', kind: 'mono' },
        { key: 'status', label: 'Status', kind: 'status' },
        { key: 'eligible_for_direct_payment', label: 'Direct payment', kind: 'bool' },
      ],
      filters: ['status', 'search'],
      title: (r) => r.legal_name,
      create: { label: 'Add an institution', path: '/v1/institutions', omit: ['client_id'], fields: [{ name: 'country', hint: 'Two-letter country code.' }, { name: 'type', options: ['school', 'university', 'hospital', 'clinic', 'pharmacy', 'agency', 'utility', 'other'].map((v) => ({ value: v, label: v })) }] },
      actions: [
        { label: 'Record the bank account', path: '/v1/institutions/{id}/payee', tone: 'primary', when: (r) => !r.payee, fields: [{ name: 'account_name_evidence_id', type: 'file' }, { name: 'legal_name_evidence_id', type: 'file' }] },
        { label: 'Send account for two-person check', path: '/v1/institutions/{id}/payee-verification', when: (r) => !!r.payee && r.payee.verification_status !== 'verified', confirm: 'Two other staff with release rights then verify the account in Approvals.' },
        { label: 'Review look-alike', path: '/v1/institutions/{id}/look-alike-review', roles: ['RV'], when: (r) => r.look_alike?.status === 'open' },
        { label: 'Not eligible for direct payment', path: '/v1/institutions/{id}/eligibility', tone: 'ghost', confirm: 'A case manager proposes with the reason; a reviewer confirms or declines. No cash route is ever offered.' },
        { label: 'Runner task (paper only)', path: '/v1/institutions/{id}/runner-tasks', roles: ['CM'], tone: 'ghost', fields: [{ name: 'runner_id', source: { path: '/v1/admin/people', query: { role: 'RN' }, label: (p) => p.full_name } }], confirm: 'A runner collects an invoice or delivers a receipt. No amount and no money.' },
        { label: 'Start re-verification', path: '/v1/institutions/{id}/reverification', tone: 'ghost', when: (r) => ['not_eligible', 'not_verified', 'suspended'].includes(r.status) },
        { label: 'Edit details', path: '/v1/institutions/{id}', method: 'PATCH', tone: 'ghost', fields: [{ name: 'registration_evidence_id', type: 'file' }] },
      ],
      hide: ['contacts'],
      subs: [
        {
          label: 'Named contacts', from: 'contacts',
          columns: [{ key: 'full_name', label: 'Name', kind: 'name' }, { key: 'role_title', label: 'Role', kind: 'text' }, { key: 'phone', label: 'Phone', kind: 'mono' }, { key: 'may_confirm_invoices', label: 'Confirms bills', kind: 'bool' }],
          create: { label: 'Add contact', path: '/v1/institutions/{id}/contacts', fields: [{ name: 'evidence_id', type: 'file', label: 'Evidence of the contact (optional)' }] },
          actions: [{ label: 'Remove', path: '/v1/institutions/{parent}/contacts/{id}/removal', tone: 'ghost' }],
        },
        { label: 'Bills for this institution', path: '/v1/invoices', query: (p) => ({ institution: p.id }), link: 'invoices', columns: [{ key: 'institution_reference', label: 'Reference', kind: 'mono' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }] },
      ],
    },
    {
      key: 'invoices', label: 'Invoice checks', list: '/v1/invoices', screen: 'SCR-BO-30', subject: 'fee_invoice',
      intro: 'Check each bill with the institution\'s named contact. A bill naming any other account is flagged and cannot be approved.',
      columns: [
        { key: 'institution.name', label: 'Institution', kind: 'name' },
        { key: 'institution_reference', label: 'Reference', kind: 'mono' },
        { key: 'family_member.full_name', label: 'For', kind: 'text' },
        { key: 'amount', label: 'Amount', kind: 'money' },
        { key: 'check_status', label: 'Check', kind: 'status' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'check_status'],
      title: (r) => `${r.institution?.name ?? 'Bill'} · ${r.institution_reference}`,
      actions: [
        { label: 'Record the check', path: '/v1/invoices/{id}/checks', tone: 'primary', when: (r) => ['submitted', 'draft'].includes(r.status) || r.check_status === 'awaiting_check', fields: [{ name: 'contact_id', label: 'Confirmed with', source: { path: (r) => `/v1/institutions/${r.institution?.id}/contacts`, label: (c) => `${c.full_name}${c.role_title ? ', ' + c.role_title : ''}` } }] },
        { label: 'Attach the bill', path: '/v1/invoices/{id}/document', when: (r) => ['draft', 'submitted'].includes(r.status), fields: [{ name: 'evidence_id', type: 'file', required: true, label: 'Bill or fee note' }] },
        { label: 'Change payment route', path: '/v1/invoices/{id}/route', tone: 'ghost', when: (r) => ['submitted', 'checked'].includes(r.status) },
        { label: 'Prepare instruction to the bank', path: '/v1/invoices/{id}/instructions', when: (r) => r.status === 'client_approved' && r.route === 'held_funds', confirm: 'The instruction names the institution\'s verified account only. Two staff then approve it in Approvals.' },
        { label: 'Cancel bill', path: '/v1/invoices/{id}/cancellation', tone: 'ghost', when: (r) => !['paid', 'receipted', 'cancelled', 'rejected', 'instructed'].includes(r.status) },
      ],
    },
    {
      key: 'payments', label: 'Fee payments', list: '/v1/fee-payments', subject: 'fee_payment',
      intro: 'Client-direct payments need the institution to confirm receipt. Every payment needs the institution\'s receipt.',
      columns: [
        { key: 'invoice.institution', label: 'Institution', kind: 'text' },
        { key: 'invoice.reference', label: 'Bill', kind: 'mono' },
        { key: 'amount', label: 'Amount', kind: 'money' },
        { key: 'route', label: 'Route', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
        { key: 'receipt_due_at', label: 'Receipt due', kind: 'date' },
      ],
      filters: ['status'],
      title: (r) => `${r.invoice?.institution ?? 'Payment'} · ${r.invoice?.reference ?? ''}`,
      actions: [
        { label: 'Institution confirms receipt', path: '/v1/fee-payments/{id}/institution-confirmation', tone: 'primary', when: (r) => r.route === 'client_direct' && ['awaiting_client_payment', 'client_reported'].includes(r.status), omit: ['contact_id'], fields: [{ name: 'received', default: true }, { name: 'evidence_id', type: 'file', label: 'Receipt or call note (optional)' }] },
        { label: 'Attach the receipt', path: '/v1/fee-payments/{id}/receipts', tone: 'primary', when: (r) => ['paid', 'receipt_overdue'].includes(r.status), fields: [{ name: 'evidence_id', type: 'file', required: true, label: 'Institution receipt' }, { name: 'confirmation_evidence_id', type: 'file', label: 'Confirmation of enrolment or treatment (optional)' }] },
      ],
    },
    {
      key: 'schedules', label: 'Schedules', list: '/v1/fee-schedules',
      intro: 'Recurring bills per term or month. Nothing is paid until the client approves each one. Silence is never approval.',
      columns: [
        { key: 'label', label: 'Schedule', kind: 'name' },
        { key: 'institution_name', label: 'Institution', kind: 'text' },
        { key: 'period', label: 'Every', kind: 'text' },
        { key: 'expected', label: 'Expected', kind: 'money' },
        { key: 'next_due_on', label: 'Next due', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      actions: [{ label: 'Change schedule', path: '/v1/fee-schedules/{id}', method: 'PATCH', tone: 'ghost' }],
    },
    {
      key: 'runner-tasks', label: 'Runner tasks', list: '/v1/fee-runner-tasks', subject: 'fee_runner_task',
      intro: 'Paper only: collect an invoice or deliver a receipt. A runner never carries money and is never a payee.',
      columns: [
        { key: 'institution_name', label: 'Institution', kind: 'name' },
        { key: 'kind', label: 'Task', kind: 'text' },
        { key: 'runner_name', label: 'Runner', kind: 'text' },
        { key: 'due_at', label: 'Due', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Record as done', path: '/v1/fee-runner-tasks/{id}/completion', tone: 'primary', when: (r) => r.status === 'open', fields: [{ name: 'evidence_id', type: 'file', label: 'Photo or signed note' }] },
        { label: 'Cancel task', path: '/v1/fee-runner-tasks/{id}/cancellation', tone: 'ghost', roles: ['CM'], when: (r) => r.status === 'open' },
      ],
    },
    {
      key: 'family', label: 'Family statements', list: '/v1/invoices', idKey: 'family_member.id', detail: '/v1/family-members/{id}/statement',
      intro: 'One statement per family member: bills, payments, receipts and what is held at the bank, in date order.',
      columns: [
        { key: 'family_member.full_name', label: 'Family member', kind: 'name' },
        { key: 'family_member.relationship', label: 'Relationship', kind: 'text' },
        { key: 'institution.name', label: 'Latest institution', kind: 'text' },
      ],
      title: (r) => `Statement · ${r.family_member?.full_name ?? r.family_member_name ?? ''}`,
      subs: [{ label: 'Issued statement PDFs', path: '/v1/family-members/{id}/statement-pdfs', note: 'The client issues these. Each carries its SHA-256.' }],
    },
  ],
};

