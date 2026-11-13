import type { SectionSpec } from '../spec';
import { paymentApproval, paymentColumns, paymentReject } from './construction';

export const projects: SectionSpec = {
  href: '/projects',
  title: 'Project funds',
  screens: 'EP-PRJ',
  intro: 'Money for a project at home goes to checked suppliers against their invoices, never as cash to the person running it. Suppliers and the runner have background checks; large sums have an anti-money-laundering review.',
  resources: [
    {
      key: 'projects', label: 'Projects', list: '/v1/projects', listQuery: { type: 'funds' }, subject: 'bld_project',
      columns: [
        { key: 'title', label: 'Project', kind: 'name' },
        { key: 'runner_name', label: 'Run by', kind: 'text' },
        { key: 'budget', label: 'Budget', kind: 'money' },
        { key: 'payment_route', label: 'Route', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Run background checks', path: '/v1/projects/{id}/background-checks', tone: 'primary', when: (r) => r.status === 'setup' },
        { label: 'Open the escrow', path: '/v1/projects/{id}/escrow', when: (r) => r.payment_route === 'escrow' && !r.escrow_id },
        { label: 'Start', path: '/v1/projects/{id}/start', when: (r) => r.status === 'setup' },
        { label: 'Cancel project', path: '/v1/projects/{id}/cancellation', tone: 'ghost', when: (r) => !['completed', 'cancelled'].includes(r.status) },
      ],
      subs: [
        {
          label: 'Suppliers', path: '/v1/projects/{id}/suppliers', link: 'suppliers',
          columns: [{ key: 'name', label: 'Supplier', kind: 'name' }, { key: 'bank_name', label: 'Bank', kind: 'text' }, { key: 'account_last4', label: 'Ending', kind: 'mono' }, { key: 'payee_verified', label: 'Payee verified', kind: 'bool' }, { key: 'status', label: 'Status', kind: 'status' }],
          create: { label: 'Add supplier', path: '/v1/projects/{id}/suppliers' },
        },
        {
          label: 'Background checks', path: '/v1/projects/{id}/background-checks',
          columns: [{ key: 'subject_name', label: 'Who', kind: 'name' }, { key: 'subject_kind', label: 'Role', kind: 'text' }, { key: 'level', label: 'Level', kind: 'text' }, { key: 'status', label: 'Status', kind: 'status' }],
          actions: [{ label: 'Record result', path: '/v1/background-checks/{id}/result', tone: 'primary', when: (c) => c.status === 'pending', fields: [{ name: 'evidence_id', type: 'file', upload: { subject_type: 'prj_background_check' } }] }],
        },
        { label: 'Anti-money-laundering review', path: '/v1/projects/{id}/aml-review', link: (r) => `/projects/aml/${r.project_id ?? r.project}`, note: 'Opened when the project needs one. A reviewer decides.' },
        {
          label: 'Invoices', path: '/v1/projects/{id}/invoices', link: 'invoices',
          columns: [{ key: 'number', label: 'Invoice', kind: 'mono' }, { key: 'supplier_name', label: 'Supplier', kind: 'name' }, { key: 'amount', label: 'Amount', kind: 'money' }, { key: 'status', label: 'Status', kind: 'status' }],
          create: { label: 'Record invoice', path: '/v1/projects/{id}/invoices', fields: [
            { name: 'supplier_id', label: 'Supplier', source: { path: '/v1/projects/{id}/suppliers', label: (s) => `${s.name} (${s.status})` } },
            { name: 'milestone_id', label: 'Stage', source: { path: '/v1/milestones', label: (m) => `${m.seq}. ${m.name}` } },
            { name: 'evidence_ids', type: 'files', required: true, upload: { subject_type: 'bld_project' } },
          ] },
        },
        { label: 'Payments', path: '/v1/projects/{id}/payments', link: (r) => `/construction/payments/${r.id}`, columns: paymentColumns },
      ],
    },
    {
      key: 'suppliers', label: 'Supplier', list: '/v1/projects', detail: '/v1/project-suppliers/{id}', hidden: true, subject: 'prj_supplier', columns: [],
      actions: [
        { label: 'Record verified payee', path: '/v1/project-suppliers/{id}/payee', tone: 'primary', when: (r) => !r.payee_verified, fields: [
          { name: 'payee_id', label: 'Existing verified payee (optional)', source: { path: '/v1/payees', query: { status: 'verified' }, label: (p) => `${p.legal_name} · ending ${p.account_last4}` } },
          { name: 'legal_name_evidence_id', type: 'file' }, { name: 'account_name_evidence_id', type: 'file' },
        ] },
        { label: 'Edit supplier', path: '/v1/project-suppliers/{id}', method: 'PATCH', tone: 'ghost' },
      ],
    },
    {
      key: 'invoices', label: 'Invoice', list: '/v1/projects', detail: '/v1/project-invoices/{id}', hidden: true, subject: 'prj_invoice', columns: [],
      actions: [
        { label: 'Accept invoice', path: '/v1/project-invoices/{id}/decision', tone: 'primary', fixed: { decision: 'accept' }, only: [], when: (r) => r.status === 'submitted', confirm: 'The supplier and amount match the evidence. A payment to the supplier\'s verified account is then prepared for the client\'s approval.' },
        { label: 'Reject invoice', path: '/v1/project-invoices/{id}/decision', tone: 'ghost', fixed: { decision: 'reject' }, fields: [{ name: 'reason', type: 'textarea', required: true }], when: (r) => r.status === 'submitted' },
      ],
    },
    {
      key: 'aml', label: 'AML review', list: '/v1/projects', detail: '/v1/projects/{id}/aml-review', hidden: true, columns: [],
      actions: [{ label: 'Decide', path: '/v1/aml-reviews/{id}/decision', roles: ['RV'], tone: 'primary' }],
    },
    {
      key: 'payments', label: 'Supplier payments', list: '/v1/project-payments', listQuery: {}, subject: 'bld_payment',
      intro: 'The client approves first, then two different staff with a fresh code. Paid only to a verified supplier.',
      columns: paymentColumns,
      filters: ['status'],
      title: (r) => r.label,
      actions: [paymentApproval, paymentReject],
    },
  ],
};
