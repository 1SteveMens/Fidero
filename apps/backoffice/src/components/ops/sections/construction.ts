import type { ActionSpec, ColKind, SectionSpec } from '../spec';

const panel = (kind: string) => ({ path: '/v1/panel-members', query: { kind, status: 'active' }, label: (m: Record<string, unknown>) => String(m.name) });

/** Release approvals: on black, code first, then press and hold (03, 6.1d). */
export const paymentApproval: ActionSpec = {
  label: 'Approve release', path: '/v1/project-payments/{id}/approvals', tone: 'primary', ink: true, mfa: true, hold: true, roles: ['RV', 'AD'],
  fixed: { decision: 'approve' }, only: ['note'],
  when: (r) => r.status === 'client_approved',
  confirm: (r) => `Release ${r.amount?.amount ?? ''} ${r.amount?.currency ?? ''} to ${r.payee?.legal_name ?? r.payee?.name ?? 'the verified payee'}. The client approved first. A different person must give the second approval.`,
};
export const paymentReject: ActionSpec = { label: 'Reject release', path: '/v1/project-payments/{id}/approvals', tone: 'ghost', mfa: true, roles: ['RV', 'AD'], fixed: { decision: 'reject' }, only: ['note'], when: (r) => r.status === 'client_approved' };

export const paymentColumns = [
  { key: 'label', label: 'Payment', kind: 'name' as ColKind },
  { key: 'payee', label: 'Payee', kind: 'name' as ColKind },
  { key: 'amount', label: 'Amount', kind: 'money' as ColKind },
  { key: 'route', label: 'Route', kind: 'text' as ColKind },
  { key: 'status', label: 'Status', kind: 'status' as ColKind },
];

export const construction: SectionSpec = {
  href: '/construction',
  title: 'Construction',
  screens: 'SCR-BO-14 · SCR-BO-15',
  intro: 'Build in stages. Each milestone is paid only after app evidence, an independent inspection and the client\'s approval, then two staff approvals. The quantity surveyor prices the work; re-pricing in cedis is shown to the client.',
  resources: [
    {
      key: 'projects', label: 'Projects', list: '/v1/projects', subject: 'bld_project',
      columns: [
        { key: 'title', label: 'Project', kind: 'name' },
        { key: 'type', label: 'Type', kind: 'text' },
        { key: 'contractor_name', label: 'Contractor', kind: 'text' },
        { key: 'budget', label: 'Budget', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'type'],
      actions: [
        { label: 'Appoint quantity surveyor', path: '/v1/projects/{id}/quantity-surveyor', tone: 'primary', when: (r) => !r.quantity_surveyor_id && r.status === 'setup', fields: [{ name: 'member_id', label: 'Quantity surveyor', source: panel('quantity_surveyor') }] },
        { label: 'Record bill of quantities', path: '/v1/projects/{id}/boq', when: (r) => r.status === 'setup', fields: [{ name: 'evidence_ids', type: 'files', required: true }] },
        { label: 'Appoint contractor', path: '/v1/projects/{id}/contractor', when: (r) => !r.contractor_id && r.status === 'setup', fields: [{ name: 'member_id', label: 'Contractor', source: panel('contractor') }] },
        { label: 'Assign inspector', path: '/v1/projects/{id}/inspector-assignments', when: (r) => !r.inspector_id, fields: [{ name: 'member_id', label: 'Inspector with no link to the contractor', source: panel('inspector') }] },
        { label: 'Record signed contract', path: '/v1/projects/{id}/contract', when: (r) => !r.contract_signed_at, fields: [{ name: 'evidence_ids', type: 'files', required: true }] },
        { label: 'Open the escrow', path: '/v1/projects/{id}/escrow', when: (r) => r.payment_route === 'escrow' && !r.escrow_id, confirm: 'Asks the partner bank to open the escrow. Tenmina never holds the money.' },
        { label: 'Start the build', path: '/v1/projects/{id}/start', when: (r) => r.status === 'setup' },
        { label: 'Record handover', path: '/v1/projects/{id}/handover', when: (r) => r.status === 'active', fields: [{ name: 'evidence_ids', type: 'files' }] },
        { label: 'Resume', path: '/v1/projects/{id}/resumption', when: (r) => r.status === 'paused', fields: [{ name: 'contractor_id', label: 'New contractor (optional)', source: panel('contractor') }] },
        { label: 'Cancel project', path: '/v1/projects/{id}/cancellation', tone: 'ghost', when: (r) => !['completed', 'cancelled'].includes(r.status) },
      ],
      subs: [
        { label: 'Dashboard', path: '/v1/projects/{id}/dashboard' },
        {
          label: 'Milestones', path: '/v1/milestones', query: (p) => ({ project_id: p.id }), link: 'milestones',
          columns: [{ key: 'seq', label: '#', kind: 'mono' }, { key: 'name', label: 'Milestone', kind: 'name' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'fraud_flagged', label: 'Flagged', kind: 'bool' }, { key: 'status', label: 'Status', kind: 'status' }],
        },
        { label: 'Bill of quantities', path: '/v1/projects/{id}/boq' },
        {
          label: 'Variations', path: '/v1/projects/{id}/variations',
          columns: [{ key: 'description', label: 'Change', kind: 'text' }, { key: 'cost_change', label: 'Cost', kind: 'money' }, { key: 'time_effect_days', label: 'Days', kind: 'mono' }, { key: 'status', label: 'Status', kind: 'status' }],
          create: { label: 'Propose variation', path: '/v1/projects/{id}/variations', fields: [{ name: 'milestone_id', label: 'Milestone', source: { path: '/v1/milestones', query: {}, label: (m) => `${m.seq}. ${m.name}` } }] },
        },
        { label: 'Payments', path: '/v1/projects/{id}/payments', link: 'payments', columns: paymentColumns },
        {
          label: 'Materials orders', path: '/v1/projects/{id}/materials-orders',
          columns: [{ key: 'description', label: 'Materials', kind: 'text' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }],
          actions: [{ label: 'Record delivery', path: '/v1/materials-orders/{id}/deliveries', when: (o) => o.status === 'paid', fields: [{ name: 'evidence_ids', type: 'files', required: true, upload: { subject_type: 'bld_materials_order' } }] }],
        },
      ],
    },
    {
      key: 'milestones', label: 'Milestone review', list: '/v1/milestones', subject: 'milestone', screen: 'SCR-BO-14',
      intro: 'Submissions with server flags, the evidence check and the inspector\'s result. A flagged submission waits for Field and devices.',
      columns: [
        { key: 'name', label: 'Milestone', kind: 'name' },
        { key: 'amount', label: 'Amount', kind: 'money' },
        { key: 'submissions', label: 'Submissions', kind: 'mono' },
        { key: 'fraud_flagged', label: 'Flagged', kind: 'bool' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Accept evidence', path: '/v1/milestones/{id}/evidence-review', tone: 'primary', fixed: { decision: 'accept' }, only: ['note'], when: (r) => r.status === 'submitted' },
        { label: 'Return evidence', path: '/v1/milestones/{id}/evidence-review', tone: 'ghost', fixed: { decision: 'return' }, fields: [{ name: 'reason', type: 'textarea', required: true }], when: (r) => r.status === 'submitted' },
        { label: 'Schedule inspection', path: '/v1/milestones/{id}/inspections', when: (r) => r.status === 'evidence_checked', fields: [{ name: 'inspector_id', label: 'Inspector', source: panel('inspector') }] },
        { label: 'Prepare release instruction', path: '/v1/milestones/{id}/release-instructions', when: (r) => r.status === 'client_approved', confirm: 'Names the contractor\'s verified account. Two staff approve it in Approvals.' },
      ],
      subs: [
        { label: 'Inspections', path: '/v1/milestones/{id}/inspections', link: 'inspections' },
        { label: 'Re-pricing', path: '/v1/milestones/{id}/reprices', note: 'Cedi re-pricing shown to the client before approval.' },
      ],
    },
    {
      key: 'inspections', label: 'Inspections', list: '/v1/inspections', subject: 'milestone_inspection',
      columns: [
        { key: 'inspector_name', label: 'Inspector', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'scheduled_for', label: 'Date', kind: 'date' },
        { key: 'outcome', label: 'Outcome', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [{ label: 'Assign inspector', path: '/v1/inspections/{id}/assignment', tone: 'primary', when: (r) => r.status === 'scheduled', fields: [{ name: 'inspector_id', label: 'Inspector', source: panel('inspector') }] }],
      subs: [{ label: 'Defects', from: 'defects' }],
    },
    {
      key: 'defects', label: 'Defects', list: '/v1/defects', subject: 'defect',
      columns: [
        { key: 'description', label: 'Defect', kind: 'name' },
        { key: 'value', label: 'Value', kind: 'money' },
        { key: 'fixed_at', label: 'Fixed', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => r.description,
      actions: [{ label: 'Close with evidence', path: '/v1/defects/{id}/close', tone: 'primary', when: (r) => r.status === 'fixed' }],
    },
    {
      key: 'payments', label: 'Project payments', list: '/v1/project-payments', subject: 'bld_payment',
      intro: 'The client approves first. Then two different staff approve with a fresh code.',
      columns: paymentColumns,
      filters: ['status'],
      title: (r) => r.label,
      actions: [paymentApproval, paymentReject, { label: 'Withdraw', path: '/v1/project-payments/{id}/withdrawal', tone: 'ghost', when: (r) => ['preparing', 'awaiting_client'].includes(r.status) }],
    },
    {
      key: 'panel', label: 'Panel', list: '/v1/panel-members', screen: 'SCR-BO-15', subject: 'panel_member',
      intro: 'Contractors, inspectors, quantity surveyors and developers, with documents, conflict links and track record. An inspector linked to a contractor cannot inspect their work.',
      columns: [
        { key: 'name', label: 'Member', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'check_outcome', label: 'Checks', kind: 'status' },
        { key: 'payee_verified', label: 'Payee verified', kind: 'bool' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'kind'],
      create: { label: 'Add a panel member', path: '/v1/panel-members' },
      actions: [
        { label: 'Run checks', path: '/v1/panel-members/{id}/checks', when: (r) => r.status === 'pending' },
        { label: 'Add documents', path: '/v1/panel-members/{id}/documents', tone: 'ghost', fields: [{ name: 'evidence_ids', type: 'files', required: true }] },
        { label: 'Record payee', path: '/v1/panel-members/{id}/payee', tone: 'ghost', when: (r) => !r.payee_verified, fields: [{ name: 'legal_name_evidence_id', type: 'file' }, { name: 'account_name_evidence_id', type: 'file' }] },
        { label: 'Approve to panel', path: '/v1/panel-members/{id}/approval', tone: 'primary', when: (r) => r.status === 'vetted' },
        { label: 'Suspend', path: '/v1/panel-members/{id}/suspension', tone: 'ghost', when: (r) => r.status === 'active' },
        { label: 'Reinstate', path: '/v1/panel-members/{id}/reinstatement', when: (r) => r.status === 'suspended' },
        { label: 'Remove', path: '/v1/panel-members/{id}/removals', tone: 'danger', when: (r) => r.status !== 'removed' },
      ],
      subs: [
        {
          label: 'Conflict links', path: '/v1/panel-members/{id}/conflict-links',
          create: { label: 'Add conflict link', path: '/v1/panel-members/{id}/conflict-links', fields: [{ name: 'other_id', label: 'Linked member', source: { path: '/v1/panel-members', label: (m) => `${m.name} (${m.kind})` } }] },
        },
        { label: 'Track record', path: '/v1/panel-members/{id}/track-record' },
      ],
    },
  ],
};
