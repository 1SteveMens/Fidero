/* Types and links for the professionals' pages (/work). */
import type { Money } from '@tenmina/api-client';

export type Task = {
  id: string; case: string; case_reference: string; step_key: string; title: string; owner_role: string;
  assignee: { id: string; name: string } | null; due_at: string | null; required_evidence: string[];
  waiting_for: string[]; site_visit: boolean; search_kind: string; review_step: boolean; status: string;
  completed_at: string | null; is_overdue: boolean; missing_evidence: string[]; notice: string; row_version: number;
};

export type InboxItem = {
  subject_type: string; subject_id: string; title: string; kind: string; status: string; address?: string;
  required_evidence: { key: string; label: string; media: string; required: boolean }[];
  checklist: { key: string; label: string }[]; plan_items: unknown[]; accepts_submissions: boolean;
  state_reason: string; due_at: string | null; details: Record<string, unknown>;
};

export type ReportRow = {
  id: string; reference: string; case: string; case_reference: string; version: number; status: string;
  overall_verdict: string | null; submitted_at: string | null; released_at: string | null; created_at: string;
};

export type Payable = {
  id: string; work_kind: string; case_reference: string | null; accepted_at: string | null; unit_rate: Money;
  quantity: string; gross: Money; withholding: Money; other_deductions: Money; net: Money; due_by: string | null;
  overdue: boolean; status: string; hold_reason: string; hold_note: string; run_reference: string | null;
  paid_at: string | null; created_at: string; role: string; cancel_reason: string;
};

/** Where an item from the field inbox opens in the portal. */
export function inboxHref(i: InboxItem): string {
  switch (i.subject_type) {
    case 'task': return `/work/tasks/${i.subject_id}`;
    case 'milestone_inspection': return `/work/inspections/${i.subject_id}`;
    case 'property_inspection': return `/work/property-inspections/${i.subject_id}`;
    case 'care_visit': return `/work/visits/${i.subject_id}`;
    case 'errand_step': return `/work/errands/${String(i.details?.errand_id ?? '')}`;
    default: return '/work/field';
  }
}

export const WORK_KIND: Record<string, string> = {
  report_section: 'Report section', site_visit: 'Site visit', inspection: 'Inspection', bill_of_quantities: 'Bill of quantities',
  errand: 'Errand', recheck: 'Re-check', month: 'Month of runner work', runner_month: 'Month of runner work', care_visit: 'Care visit',
};

/** Why a payable is held, in plain words and never about the result of the work (5.6b, RUL-26). */
export const HOLD_TEXT: Record<string, string> = {
  fraud_review: 'Held: we are checking the evidence on this job. Not about the result.',
  misconduct_review: 'Held: a review is open. Not about the result.',
  payee_not_verified: 'Held: we have not yet confirmed your bank account.',
  agreement_suspended: 'Held: your agreement is paused.',
};
