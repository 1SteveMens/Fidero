import type { SectionSpec } from '../spec';

export const events: SectionSpec = {
  href: '/events',
  title: 'Events',
  screens: 'EP-EVT',
  intro: 'Funerals, weddings and naming ceremonies paid through checked vendors. Deposits against a signed quote; the balance against delivery evidence or a family confirmation. Two staff approve every payment.',
  resources: [
    {
      key: 'events', label: 'Events', list: '/v1/events', subject: 'evt_event',
      columns: [
        { key: 'name', label: 'Event', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'event_date', label: 'Date', kind: 'date' },
        { key: 'budget', label: 'Budget', kind: 'money' },
        { key: 'escrow_status', label: 'Escrow', kind: 'status' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      hide: ['vendors', 'row_version'],
      actions: [
        { label: 'Open the escrow', path: '/v1/events/{id}/escrow', when: (r) => !r.escrow && r.status === 'planning', confirm: 'Asks the partner bank to open an escrow for this event. Tenmina never holds the money.' },
        { label: 'Change budget', path: '/v1/events/{id}/budget', tone: 'ghost', when: (r) => !['closed', 'cancelled'].includes(r.status) },
        { label: 'Close event', path: '/v1/events/{id}/close', tone: 'ghost', when: (r) => r.status === 'in_progress' || r.status === 'funded' },
        { label: 'Cancel event', path: '/v1/events/{id}/cancel', tone: 'ghost', when: (r) => !['closed', 'cancelled'].includes(r.status) },
      ],
      subs: [
        {
          label: 'Vendors', from: 'vendors', link: 'vendors', note: 'A vendor stays Unverified until two staff check its registration and account name.',
          columns: [{ key: 'name', label: 'Vendor', kind: 'name' }, { key: 'kind', label: 'Kind', kind: 'text' }, { key: 'quote', label: 'Quote', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }],
          create: { label: 'Add vendor', path: '/v1/events/{id}/vendors', omit: ['payee_id'], fields: [{ name: 'registration_evidence_id', type: 'file', upload: { subject_type: 'evt_event' } }, { name: 'quote_evidence_id', type: 'file', upload: { subject_type: 'evt_event' } }] },
        },
        {
          label: 'Vendor payments', path: '/v1/events/{id}/vendor-payments', link: 'vendor-payments',
          columns: [{ key: 'vendor_name', label: 'Vendor', kind: 'name' }, { key: 'kind', label: 'Part', kind: 'text' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }],
          create: { label: 'Propose a payment', path: '/v1/events/{id}/vendor-payments', fields: [
            { name: 'vendor_id', label: 'Vendor', options: (p) => ((p.vendors as { id: string; name: string; status: string }[]) ?? []).map((v) => ({ value: v.id, label: `${v.name} (${v.status})` })) },
            { name: 'quote_evidence_id', type: 'file', upload: { subject_type: 'evt_event' } },
            { name: 'invoice_evidence_id', type: 'file', upload: { subject_type: 'evt_event' } },
            { name: 'delivery_evidence_ids', type: 'files', upload: { subject_type: 'evt_event' } },
          ] },
        },
        { label: 'Receipts', path: '/v1/events/{id}/receipts' },
      ],
    },
    {
      key: 'vendors', label: 'Vendor', list: '/v1/events', detail: '/v1/event-vendors/{id}', hidden: true, subject: 'evt_vendor',
      columns: [],
      actions: [
        { label: 'Record the vendor\'s account', path: '/v1/event-vendors/{id}/payee', tone: 'primary', when: (r) => !r.payee || r.status !== 'verified', fields: [{ name: 'account_name_evidence_id', type: 'file' }, { name: 'legal_name_evidence_id', type: 'file' }], confirm: 'Two other staff then verify the account in Approvals before any payment.' },
        { label: 'Remove vendor', path: '/v1/event-vendors/{id}/remove', tone: 'ghost' },
      ],
    },
    {
      key: 'vendor-payments', label: 'Vendor payment', list: '/v1/events', detail: '/v1/vendor-payments/{id}', hidden: true, subject: 'event_vendor_payment',
      columns: [],
      actions: [
        { label: 'Attach delivery evidence', path: '/v1/vendor-payments/{id}/evidence', tone: 'primary', when: (r) => ['proposed', 'evidenced'].includes(r.status) },
        { label: 'Ask the family to confirm', path: '/v1/vendor-payments/{id}/family-confirmation-requests', when: (r) => ['proposed', 'evidenced'].includes(r.status), confirm: 'Sends a one-time code to the event\'s named family confirmer.' },
        { label: 'Record family code', path: '/v1/vendor-payments/{id}/family-confirmations', tone: 'ghost', when: (r) => ['proposed', 'evidenced'].includes(r.status) },
        { label: 'Prepare instruction to the bank', path: '/v1/vendor-payments/{id}/instructions', when: (r) => r.status === 'client_approved', confirm: 'Names the vendor\'s verified account. Two staff approve it in Approvals.' },
        { label: 'Reject', path: '/v1/vendor-payments/{id}/reject', tone: 'ghost', when: (r) => !['paid', 'instructed', 'rejected'].includes(r.status) },
      ],
    },
  ],
};
