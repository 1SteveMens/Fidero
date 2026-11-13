import type { SectionSpec } from '../spec';

const open = (r: Record<string, unknown>) => !['closed', 'withdrawn'].includes(String(r.status));
const waitingDecision = (r: Record<string, unknown>) => ((r.decisions as { status?: string }[]) ?? []).some((d) => ['pending', 'proposed', 'awaiting_approval', 'pending_approval'].includes(String(d.status)));

export const disputes: SectionSpec = {
  href: '/disputes',
  title: 'Disputes',
  screens: 'SCR-BO-17',
  intro: 'A dispute freezes the money it touches. Each side states its case by the deadlines. A decision needs reasons and two staff approvals, never a party to the matter. Mediation outcomes are approved the same way.',
  resources: [
    {
      key: 'disputes', label: 'Disputes', list: '/v1/disputes', subject: 'dispute',
      columns: [
        { key: 'reference', label: 'Dispute', kind: 'ref' },
        { key: 'subject_label', label: 'About', kind: 'name' },
        { key: 'category', label: 'Category', kind: 'text' },
        { key: 'decision_due', label: 'Decision due', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      hide: ['parties', 'statements', 'decisions', 'my_side'],
      links: { escrow_id: '/escrow', project_id: '/construction/projects', listing_id: '/listings/listings', milestone_id: '/construction/milestones' },
      actions: [
        { label: 'Add staff statement', path: '/v1/disputes/{id}/statements', tone: 'ghost', when: open, fields: [{ name: 'evidence_ids', type: 'files' }] },
        { label: 'Evidence complete', path: '/v1/disputes/{id}/evidence-complete', when: (r) => r.status === 'evidence', confirm: 'Closes the evidence stage. The decision stage starts.' },
        { label: 'Propose decision', path: '/v1/disputes/{id}/decisions', tone: 'primary', when: (r) => ['decision', 'evidence', 'awaiting_response'].includes(String(r.status)) && !waitingDecision(r), omit: ['details'], confirm: 'Write the reasons in plain words. Two other staff approve before it takes effect.' },
        { label: 'Approve decision', path: '/v1/disputes/{id}/decision-approvals', tone: 'primary', ink: true, mfa: true, hold: true, roles: ['RV', 'AD'], fixed: { decision: 'approve' }, only: ['note'], when: waitingDecision, confirm: 'You are not a party and did not approve the disputed release. A different person gives the other approval.' },
        { label: 'Reject decision', path: '/v1/disputes/{id}/decision-approvals', tone: 'ghost', mfa: true, roles: ['RV', 'AD'], fixed: { decision: 'reject' }, only: ['note'], when: waitingDecision },
        { label: 'Refer to mediation', path: '/v1/disputes/{id}/referrals', roles: ['RV'], when: (r) => open(r) && r.status !== 'referred' },
        { label: 'Record mediation outcome', path: '/v1/disputes/{id}/mediation-outcomes', tone: 'primary', when: (r) => r.status === 'referred', omit: ['details'] },
      ],
      subs: [
        { label: 'Parties', from: 'parties', columns: [{ key: 'name', label: 'Party', kind: 'name' }, { key: 'side', label: 'Side', kind: 'text' }, { key: 'role', label: 'Role', kind: 'text' }, { key: 'responded_at', label: 'Responded', kind: 'when' }, { key: 'missed_response', label: 'Missed', kind: 'bool' }] },
        { label: 'Statements', from: 'statements', columns: [{ key: 'party_name', label: 'From', kind: 'name' }, { key: 'kind', label: 'Kind', kind: 'text' }, { key: 'text', label: 'Statement', kind: 'text' }, { key: 'created_at', label: 'When', kind: 'when' }] },
        { label: 'Decisions and approvals', from: 'decisions' },
        { label: 'Frozen while open', from: 'links', columns: [{ key: 'subject_type', label: 'What', kind: 'text' }, { key: 'subject_id', label: 'ID', kind: 'mono' }, { key: 'prior_status', label: 'Was', kind: 'status' }] },
      ],
    },
  ],
};
