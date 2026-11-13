import type { SectionSpec } from '../spec';

export const field: SectionSpec = {
  href: '/field',
  title: 'Field and devices',
  screens: 'SCR-BO-14 · EP-MOB',
  intro: 'Tenmina Field devices, the server\'s fraud flags on field evidence, and who is assigned to which site. A flagged submission waits until a reviewer clears or upholds the flag.',
  resources: [
    {
      key: 'flags', label: 'Fraud flags', list: '/v1/mobile/fraud-flags', listQuery: { status: 'open' }, detail: '/v1/mobile/fraud-flags/{id}',
      intro: 'Position outside the site, a reused photo, a time gap. Clear only with a reason you can show; uphold to stop the payment.',
      columns: [
        { key: 'kind', label: 'Flag', kind: 'name' },
        { key: 'subject_type', label: 'On', kind: 'text' },
        { key: 'created_at', label: 'Raised', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'kind'],
      title: (r) => `${String(r.kind).replace(/_/g, ' ')} flag`,
      actions: [
        { label: 'Clear flag', path: '/v1/mobile/fraud-flags/{id}/clear', tone: 'primary', roles: ['RV', 'AD', 'CM'], when: (r) => r.status === 'open', fields: [{ name: 'note', type: 'textarea', hint: 'Why the evidence still holds, in plain words.' }] },
        { label: 'Uphold flag', path: '/v1/mobile/fraud-flags/{id}/uphold', tone: 'danger', roles: ['RV', 'AD', 'CM'], when: (r) => r.status === 'open', confirm: 'The submission is rejected and any payment that depends on it stays blocked.' },
      ],
    },
    {
      key: 'all-flags', label: 'All flags', list: '/v1/mobile/fraud-flags', detail: '/v1/mobile/fraud-flags/{id}',
      columns: [
        { key: 'kind', label: 'Flag', kind: 'name' },
        { key: 'subject_type', label: 'On', kind: 'text' },
        { key: 'reviewed_at', label: 'Reviewed', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'kind'],
    },
    {
      key: 'devices', label: 'Devices', list: '/v1/mobile/devices',
      intro: 'Each field device is registered with a hardware key. Revoke a lost or tampered device at once.',
      columns: [
        { key: 'model', label: 'Device', kind: 'name' },
        { key: 'platform', label: 'Platform', kind: 'text' },
        { key: 'app_version', label: 'App', kind: 'mono' },
        { key: 'integrity_status', label: 'Integrity', kind: 'status' },
        { key: 'last_seen_at', label: 'Last seen', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => `${r.model} · ${r.platform}`,
      actions: [{ label: 'Revoke device', path: '/v1/mobile/devices/{id}/revoke', tone: 'danger', roles: ['RV', 'AD'], when: (r) => r.status === 'active', confirm: 'The device can no longer submit evidence. The person must register again.' }],
    },
    {
      key: 'assignments', label: 'Field assignments', list: '/v1/mobile/assignments',
      columns: [
        { key: 'title', label: 'Job', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'address', label: 'Where', kind: 'text' },
        { key: 'due_at', label: 'Due', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [{ label: 'Revoke assignment', path: '/v1/mobile/assignments/{id}/revoke', tone: 'ghost', when: (r) => r.status === 'active' }],
    },
  ],
};
