import type { SectionSpec } from '../spec';

export const partners: SectionSpec = {
  href: '/partners',
  title: 'Partner API',
  screens: 'SCR-BO-21',
  intro: 'Banks and other partners that call Tenmina\'s API. Each has scopes, a rate limit and a monthly quota. A partner sees a client\'s report only with that client\'s consent.',
  resources: [
    {
      key: 'clients', label: 'Partner clients', list: '/v1/admin/partner-clients', roles: ['AD'],
      columns: [
        { key: 'name', label: 'Client', kind: 'name' },
        { key: 'partner_name', label: 'Partner', kind: 'text' },
        { key: 'client_id', label: 'Client ID', kind: 'mono' },
        { key: 'last_used_at', label: 'Last used', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      create: { label: 'New partner client', path: '/v1/admin/partner-clients', showResult: true, fields: [
        { name: 'partner_id', label: 'Partner', source: { path: '/v1/admin/partners', label: (p) => `${p.name} (${p.kind})` } },
        { name: 'scopes', hint: 'One per line, e.g. orders:write, reports:read, plots:status.' },
      ] },
      actions: [
        { label: 'Rotate secret', path: '/v1/admin/partner-clients/{id}/rotate-secret', mfa: true, showResult: true, when: (r) => r.status === 'active', confirm: 'The old secret stops working now. The new one is shown once.' },
        { label: 'Change status', path: '/v1/admin/partner-clients/{id}/status', tone: 'ghost', mfa: true },
        { label: 'Edit scopes and limits', path: '/v1/admin/partner-clients/{id}', method: 'PATCH', tone: 'ghost' },
        { label: 'Usage statement', path: '/v1/admin/partner-clients/{id}/usage-statements', tone: 'ghost', fields: [{ name: 'month', hint: 'YYYY-MM' }], showResult: true },
      ],
      subs: [
        { label: 'Usage this month', path: '/v1/admin/partner-clients/{id}/usage' },
        { label: 'Webhook deliveries', path: '/v1/admin/partner-clients/{id}/deliveries', columns: [{ key: 'event', label: 'Event', kind: 'mono' }, { key: 'attempts', label: 'Attempts', kind: 'mono' }, { key: 'created_at', label: 'When', kind: 'when' }, { key: 'status', label: 'Status', kind: 'status' }] },
      ],
    },
    {
      key: 'orders', label: 'Partner orders', list: '/v1/partner-orders',
      intro: 'Orders a partner placed for a client. The client confirms; staff can confirm or decline on their behalf only with the client\'s instruction.',
      columns: [
        { key: 'reference', label: 'Order', kind: 'ref' },
        { key: 'partner_name', label: 'Partner', kind: 'name' },
        { key: 'created_at', label: 'Placed', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Confirm', path: '/v1/partner-orders/{id}/confirm', tone: 'primary', when: (r) => r.status === 'awaiting_client' },
        { label: 'Decline', path: '/v1/partner-orders/{id}/decline', tone: 'ghost', when: (r) => r.status === 'awaiting_client' },
      ],
    },
    {
      key: 'deliveries', label: 'Retry webhooks', list: '/v1/admin/partner-clients', roles: ['AD'], detail: null,
      intro: 'Sends any webhook deliveries that are due again.',
      columns: [{ key: 'name', label: 'Client', kind: 'name' }, { key: 'status', label: 'Status', kind: 'status' }],
      create: { label: 'Send due deliveries now', path: '/v1/admin/partner-webhook-deliveries', tone: 'ghost', showResult: true },
    },
  ],
};
