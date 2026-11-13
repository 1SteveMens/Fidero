import type { SectionSpec } from '../spec';

const carerSource = { path: '/v1/carers', query: { status: 'active' }, label: (c: Record<string, any>) => `${c.person?.full_name ?? 'Carer'} · ${c.areas || c.pay_route}` }; // eslint-disable-line @typescript-eslint/no-explicit-any

export const care: SectionSpec = {
  href: '/care',
  title: 'Care visits',
  screens: 'SCR-BO-28',
  intro: 'Vetted carers only. Each visit is proven in the field app and confirmed by the named family member. A carer is paid only for confirmed visits, after two staff approve.',
  resources: [
    {
      key: 'visits', label: 'Visits', list: '/v1/care-visits', subject: 'care_visit',
      intro: 'Missed, unconfirmed and disputed visits first. A call confirmation needs a second staff check before it counts.',
      columns: [
        { key: 'plan_reference', label: 'Plan', kind: 'mono' },
        { key: 'family_member.full_name', label: 'Visit for', kind: 'name' },
        { key: 'carer.name', label: 'Carer', kind: 'text' },
        { key: 'window_start', label: 'Window', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => `Visit · ${r.family_member?.full_name ?? ''}`,
      actions: [
        { label: 'Record call confirmation', path: '/v1/care-visits/{id}/confirmations', tone: 'primary', fixed: { method: 'call' }, only: ['family_member_id', 'call_note'], when: (r) => ['checked_out', 'unconfirmed'].includes(r.status), confirm: 'You spoke to the named family member. A second staff member must check this before it counts for pay.' },
        { label: 'Second check of call', path: '/v1/care-visits/{id}/call-checks', tone: 'primary', when: (r) => r.confirmation?.method === 'call' && !r.confirmation?.checked_by, fields: [{ name: 'agree', default: true, label: 'I agree the call confirms this visit' }] },
        { label: 'Reviewer decision', path: '/v1/care-visits/{id}/reviewer-decisions', roles: ['RV'], when: (r) => r.status === 'unconfirmed' || !!r.review_queued_at, confirm: 'Decide from the check-in evidence and a call to the family. Only "confirmed" makes the visit payable.' },
        { label: 'Send a new code', path: '/v1/care-visits/{id}/codes', tone: 'ghost', when: (r) => ['checked_out', 'unconfirmed'].includes(r.status) },
        { label: 'Prepare carer payment', path: '/v1/care-visits/{id}/instructions', when: (r) => r.status === 'confirmed' && !r.instruction_id, confirm: 'Only a confirmed visit is paid. The instruction names the carer\'s verified account and needs two staff approvals.' },
        { label: 'Cancel visit', path: '/v1/care-visits/{id}/cancel', tone: 'ghost', when: (r) => r.status === 'scheduled' },
      ],
    },
    {
      key: 'review', label: 'Reviewer queue', list: '/v1/care-visits', listQuery: { review: 'true' }, detail: '/v1/care-visits/{id}', roles: ['RV', 'AD'], subject: 'care_visit',
      intro: 'Visits still unconfirmed 72 hours after check-out. Decide from the evidence and a call to the family.',
      columns: [
        { key: 'plan_reference', label: 'Plan', kind: 'mono' },
        { key: 'family_member.full_name', label: 'Visit for', kind: 'name' },
        { key: 'carer.name', label: 'Carer', kind: 'text' },
        { key: 'needs_review_reason', label: 'Why', kind: 'text' },
        { key: 'review_queued_at', label: 'Queued', kind: 'when' },
      ],
      rowActions: [{ label: 'Decide', path: '/v1/care-visits/{id}/reviewer-decisions', roles: ['RV'] }],
    },
    {
      key: 'plans', label: 'Care plans', list: '/v1/care-plans',
      columns: [
        { key: 'reference', label: 'Plan', kind: 'ref' },
        { key: 'family_member.full_name', label: 'For', kind: 'name' },
        { key: 'carer', label: 'Carer', kind: 'name' },
        { key: 'visit_fee', label: 'Visit fee', kind: 'money' },
        { key: 'next_visit_at', label: 'Next visit', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Assign a carer', path: '/v1/care-plans/{id}/assignments', tone: 'primary', fields: [{ name: 'carer_id', label: 'Carer from the vetted panel', source: carerSource }], when: (r) => r.status !== 'ended' },
        { label: 'Pause plan', path: '/v1/care-plans/{id}/pause', tone: 'ghost', when: (r) => r.status === 'active' },
        { label: 'Resume plan', path: '/v1/care-plans/{id}/resume', when: (r) => r.status === 'paused' },
        { label: 'End plan', path: '/v1/care-plans/{id}/end', tone: 'ghost', when: (r) => r.status !== 'ended' },
      ],
      subs: [{ label: 'Visits', path: '/v1/care-visits', query: (p) => ({ plan: p.id }), link: 'visits', columns: [{ key: 'window_start', label: 'Window', kind: 'when' }, { key: 'carer.name', label: 'Carer', kind: 'text' }, { key: 'status', label: 'Status', kind: 'status' }] }],
    },
    {
      key: 'carers', label: 'Carer panel', list: '/v1/carers',
      intro: 'Identity, references, background check and training, with the track record. A carer missing any item cannot be assigned.',
      columns: [
        { key: 'person.full_name', label: 'Carer', kind: 'name' },
        { key: 'vetting.status', label: 'Vetting', kind: 'status' },
        { key: 'vetting.valid_until', label: 'Valid until', kind: 'date' },
        { key: 'areas', label: 'Areas', kind: 'text' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      title: (r) => r.person?.full_name ?? 'Carer',
      create: { label: 'Add a vetted carer', path: '/v1/carers', fields: [{ name: 'person_id', hint: 'The person\'s ID. They must have a completed vetting (Professionals › Vetting).' }, { name: 'payee_id', source: { path: '/v1/payees', query: { status: 'verified' }, label: (p) => `${p.legal_name} · ${p.kind} · ending ${p.account_last4}` } }] },
      actions: [
        { label: 'Suspend', path: '/v1/carers/{id}/suspend', tone: 'ghost', when: (r) => r.status === 'active' },
        { label: 'Reinstate', path: '/v1/carers/{id}/reinstate', when: (r) => r.status === 'suspended' },
        { label: 'Remove for cause', path: '/v1/carers/{id}/remove', tone: 'danger', when: (r) => r.status !== 'removed', fields: [{ name: 'replacement_id', label: 'Carer who takes the future visits', source: carerSource }], confirm: 'Future visits move to the replacement. The reason feeds the track record.' },
        { label: 'Edit', path: '/v1/carers/{id}', method: 'PATCH', tone: 'ghost' },
      ],
      subs: [{ label: 'Vetting record', path: '/v1/carers/{id}/vetting' }],
    },
    {
      key: 'concerns', label: 'Concerns', list: '/v1/concerns', subject: 'care_concern',
      intro: 'Health, safety and welfare concerns raised on a visit. Restricted log. The client sees the outcome, never the carer\'s private notes.',
      columns: [
        { key: 'reference', label: 'Concern', kind: 'ref' },
        { key: 'family_member.full_name', label: 'About', kind: 'name' },
        { key: 'kind', label: 'Kind', kind: 'text' },
        { key: 'severity', label: 'Severity', kind: 'text' },
        { key: 'raised_at', label: 'Raised', kind: 'when' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Acknowledge', path: '/v1/concerns/{id}/acknowledge', tone: 'primary', when: (r) => r.status === 'open' },
        { label: 'Record action taken', path: '/v1/concerns/{id}/action', tone: 'primary', when: (r) => ['open', 'acknowledged'].includes(r.status), fields: [{ name: 'client_outcome', type: 'textarea', hint: 'What the client will see.' }] },
        { label: 'Close', path: '/v1/concerns/{id}/close', tone: 'ghost', when: (r) => r.status === 'actioned' },
      ],
    },
    {
      key: 'batches', label: 'Payment batches', list: '/v1/care-visits', listQuery: { status: 'confirmed' }, detail: '/v1/care-visits/{id}', subject: 'care_visit',
      intro: 'Confirmed visits waiting for a payment instruction. Unconfirmed visits are never included.',
      columns: [
        { key: 'carer.name', label: 'Carer', kind: 'name' },
        { key: 'family_member.full_name', label: 'Visit for', kind: 'text' },
        { key: 'confirmed_at', label: 'Confirmed', kind: 'when' },
        { key: 'fee', label: 'Fee', kind: 'money' },
      ],
      create: { label: 'Prepare this period\'s batch', path: '/v1/care-payment-batches', confirm: 'Prepares one instruction per carer for confirmed visits only. Each needs two staff approvals, and the client\'s approval above any standing amount.', showResult: true },
    },
  ],
};
