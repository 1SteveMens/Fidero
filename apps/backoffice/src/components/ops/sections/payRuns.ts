import type { SectionSpec } from '../spec';

export const payRuns: SectionSpec = {
  href: '/pay-runs',
  title: 'Payment runs',
  screens: 'SCR-BO-39 · SCR-BO-40 · SCR-BO-41',
  intro: 'Professionals are paid by Tenmina from its own operating account. One person prepares a run to a cut-off; a different person with payment rights approves it with a code. Not client money.',
  resources: [
    {
      key: 'runs', label: 'Runs', list: '/v1/pro/payment-runs',
      columns: [
        { key: 'reference', label: 'Run', kind: 'ref' },
        { key: 'cut_off_at', label: 'Cut-off', kind: 'when' },
        { key: 'line_count', label: 'Lines', kind: 'mono' },
        { key: 'total_net', label: 'Net', kind: 'money' },
        { key: 'prepared_by_name', label: 'Prepared by', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      create: {
        label: 'Prepare a run', path: '/v1/pro/payment-runs', roles: ['CM', 'RV', 'AD'], omit: ['operating_account_id'],
        confirm: 'One line per professional with payables, expenses, tax and net, up to the cut-off. Items that cannot be paid are left out with the reason.',
        goto: (res) => `/pay-runs/runs/${res.id}`,
      },
    },
  ],
};
