/* Types for the contractor's pages (/contractor). */
import type { Money } from '@tenmina/api-client';

export type Project = {
  id: string; type: string; title: string; status: string; country: string; contractor_id: string | null; contractor_name: string | null;
  budget: Money | null; payment_route: string; started_at: string | null; handover_confirmed_at: string | null; defects_period_ends_on: string | null; status_reason: string;
};
export type Milestone = {
  id: string; project_id: string; seq: number; key: string; name: string; share_pct: string; amount: Money; status: string; freeze_kind: string;
  required_evidence: { key: string; label: string; media: string; required: boolean }[]; checklist: { key: string; label: string }[];
  submitted_at: string | null; submissions: number; return_reasons: string[]; inspected_at: string | null; client_approved_at: string | null;
  paid_at: string | null; accepts_submissions: boolean; waiting_reason: string;
};
export type Variation = { id: string; milestone_id: string; description: string; cost_change: Money; time_effect_days: number; status: string; client_agreed_at: string | null; contractor_agreed_at: string | null; agreed_at: string | null; decline_reason: string; created_at: string };
export type ProjectPayment = {
  id: string; project_id: string; milestone_id: string | null; part: string; label: string; amount: Money; holdback: Money | null;
  payee: { name: string; account_last4: string; bank_name: string; verified: boolean } | null; route: string; status: string;
  client_approved_at: string | null; release_approved_at: string | null; client_paid_at: string | null; paid_at: string | null; bank_reference: string; created_at: string;
};
export type Defect = { id: string; inspection_id: string; milestone_id: string; project_id: string; description: string; value: Money; status: string; photo_evidence_ids: string[]; closing_evidence_ids: string[]; fixed_at: string | null; closed_at: string | null; note: string };

export const MILESTONE_TEXT: Record<string, string> = {
  not_started: 'Not started.', submitted: 'Evidence sent. Tenmina is checking it.', evidence_checked: 'Evidence checked. An inspection comes next.',
  returned: 'Returned. Fix what is listed and send the evidence again from Tenmina Field.', inspection_scheduled: 'Inspection booked.',
  inspected: 'Inspected.', awaiting_client: 'Waiting for the client to approve.', client_approved: 'The client approved. Two Tenmina staff approve the payment next.',
  paid: 'Paid by the bank.', frozen: 'Frozen while a dispute or review is open.',
};
