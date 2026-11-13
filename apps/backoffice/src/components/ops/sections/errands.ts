import type { SectionSpec } from '../spec';

export const errands: SectionSpec = {
  href: '/errands',
  title: 'Errands',
  screens: 'SCR-BO-32',
  intro: 'Paperwork done by vetted agents. Official fees go to the agency\'s verified account only. An errand is complete when the resulting document exists and is checked, not when someone says so.',
  resources: [
    {
      key: 'errands', label: 'Errands', list: '/v1/errands', subject: 'errand',
      columns: [
        { key: 'reference', label: 'Errand', kind: 'ref' },
        { key: 'name', label: 'What', kind: 'name' },
        { key: 'agent', label: 'Agent', kind: 'name' },
        { key: 'due_on', label: 'Due', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      hide: ['documents', 'steps'],
      actions: [
        { label: 'Assign an agent', path: '/v1/errands/{id}/assignments', tone: 'primary', when: (r) => ['funded', 'documents_pending', 'ordered', 'assigned'].includes(r.status), fields: [
          { name: 'agent_id', label: 'Agent from the vetted panel', source: { path: '/v1/errand-agents', query: { status: 'active' }, label: (a) => `${a.name} · ${a.open_errands ?? 0} open` } },
          { name: 'agency_payee_id', label: 'Agency account (verified payee)', source: { path: '/v1/payees', query: { status: 'verified' }, label: (p) => `${p.legal_name} · ending ${p.account_last4}` } },
        ] },
        { label: 'Approve agency account', path: '/v1/errands/{id}/agency-approvals', when: (r) => !!r.agency_payee && !r.agency_approved_at, confirm: 'The official fee can be paid only to this agency\'s verified account.' },
        { label: 'Check the result document', path: '/v1/errands/{id}/result-checks', tone: 'primary', when: (r) => r.status === 'result_uploaded', confirm: 'Check the document against the checklist. Accepting completes the errand, tells the client and creates the agent\'s payable (paid by Tenmina).' },
        { label: 'Confirm handover', path: '/v1/errands/{id}/handover-confirmations', when: (r) => !!r.handover && r.status !== 'handed_over' },
        { label: 'Record handover', path: '/v1/errands/{id}/handovers', when: (r) => r.status === 'completed' && !r.handover, fields: [{ name: 'evidence_id', type: 'file', label: 'Signature or photo' }] },
        { label: 'Cancel errand', path: '/v1/errands/{id}/cancel', tone: 'ghost', when: (r) => !['completed', 'handed_over', 'cancelled'].includes(r.status) },
      ],
      subs: [
        {
          label: 'Documents', from: 'documents', note: 'Accept or reject each checklist document.',
          columns: [{ key: 'label', label: 'Document', kind: 'name' }, { key: 'required', label: 'Required', kind: 'bool' }, { key: 'status', label: 'Status', kind: 'status' }, { key: 'uploaded_at', label: 'Uploaded', kind: 'when' }],
          actions: [
            { label: 'Accept', path: '/v1/errands/{parent}/documents/{key}/reviews', tone: 'primary', fixed: { accept: true }, only: [], when: (d) => d.status === 'uploaded' },
            { label: 'Reject', path: '/v1/errands/{parent}/documents/{key}/reviews', tone: 'ghost', fixed: { accept: false }, fields: [{ name: 'reason', type: 'textarea', required: true }], when: (d) => d.status === 'uploaded' },
            { label: 'Upload for client', path: '/v1/errands/{parent}/documents/{key}', tone: 'ghost', when: (d) => d.status !== 'accepted', fields: [{ name: 'evidence_id', type: 'file', required: true, upload: { subject_type: 'errand', subjectId: (_d, p) => String(p?.id) } }] },
          ],
        },
        {
          label: 'Steps and fees', from: 'steps', note: 'Each official fee needs its instruction to the agency\'s verified account, two staff approvals and the receipt before the step closes.',
          columns: [{ key: 'seq', label: '#', kind: 'mono' }, { key: 'description', label: 'Step', kind: 'name' }, { key: 'official_fee', label: 'Official fee', kind: 'money' }, { key: 'has_receipt', label: 'Receipt', kind: 'bool' }, { key: 'status', label: 'Status', kind: 'status' }],
          actions: [{ label: 'Prepare fee instruction', path: '/v1/errands/{parent}/steps/{seq}/instructions', when: (s) => Number(s.official_fee?.amount ?? 0) > 0 && !s.release_instruction_id, confirm: 'The instruction names the agency\'s verified account. Never the agent.' }],
        },
        { label: 'Payments', path: '/v1/errands/{id}/payments' },
      ],
    },
    {
      key: 'agents', label: 'Agents', list: '/v1/errand-agents',
      intro: 'Vetted errand agents. Only agents on this panel for the country can be assigned.',
      columns: [
        { key: 'name', label: 'Agent', kind: 'name' },
        { key: 'vetting.status', label: 'Vetting', kind: 'status' },
        { key: 'open_errands', label: 'Open errands', kind: 'mono' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      create: { label: 'Add a vetted agent', path: '/v1/errand-agents', fields: [{ name: 'person_id', hint: 'The person\'s ID. They need a completed vetting.' }] },
      actions: [
        { label: 'Suspend', path: '/v1/errand-agents/{id}/suspend', tone: 'ghost', when: (r) => r.status === 'active' },
        { label: 'Reinstate', path: '/v1/errand-agents/{id}/reinstate', when: (r) => r.status === 'suspended' },
        { label: 'Remove', path: '/v1/errand-agents/{id}/remove', tone: 'danger', when: (r) => r.status !== 'removed' },
      ],
    },
    {
      key: 'catalogue', label: 'Catalogue', list: '/v1/errand-catalogue', listQuery: (me) => ({ country: me?.home_country ?? '', include_incomplete: 'true' }), detail: null, filters: ['country'],
      intro: 'Errands clients can order per country, with the document checklist, official fees, Tenmina\'s charge and target time. Edit the catalogue in Admin › Configuration versions.',
      columns: [
        { key: 'name', label: 'Errand', kind: 'name' },
        { key: 'agency', label: 'Agency', kind: 'text' },
        { key: 'official_fees', label: 'Official fees', kind: 'money' },
        { key: 'tenmina_charge', label: 'Tenmina charge', kind: 'money' },
        { key: 'target_days', label: 'Target days', kind: 'mono' },
        { key: 'orderable', label: 'Orderable', kind: 'bool' },
      ],
    },
  ],
};
