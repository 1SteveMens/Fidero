/* Response shapes used by the core screens (from each module's serializers.py in api/). */
export type Ref = { id: string; name: string } | null;
export type MoneyT = { amount: string; currency: string };
export type Reason = { rule: string; code?: string; message: string };

export type Task = {
  id: string; case: string; case_reference: string; step_key: string; title: string; position: number; owner_role: string;
  assignee: Ref; second_assignee: Ref; assigned_at: string | null; due_at: string; due_change_reason: string;
  required_evidence: string[]; depends_on: string[]; waiting_for: string[]; site_visit: boolean; search_kind: string;
  review_step: boolean; status: string; completed_at: string | null; is_overdue: boolean; missing_evidence: string[]; notice: string;
};

export type StatusMessage = { id: string; template_key: string; text: string; message_date: string; next_expected_date: string | null; created_at: string };

export type Case = {
  id: string; reference: string; country: string; title: string; product_line: string; status: string; order: string | null;
  asset: string | null; client: Ref; case_manager: Ref; template_version: number; risk_flag: boolean; hold_reason: string;
  outcome: string; accepted_at: string | null; closed_at: string | null; latest_status: StatusMessage | null; created_at: string;
  subject_type?: string; subject_id?: string;
};

export type CaseDetail = Case & {
  status_messages: StatusMessage[]; tasks: Task[] | null; document_requests: DocRequest[];
  reports: { id: string; reference: string; version: number; status: string; released_at: string | null }[];
  parent_case: string | null; cancel_reason: string; refund_decision: string; outcome_note: string;
};

export type DocRequest = { id: string; case: string; title: string; description: string; due_on: string | null; status: string; received_at: string | null; received_evidence: string | null; created_at: string };
export type Message = { id: string; side: string; sender: Ref; body: string; created_at: string };
export type RiskScreen = { id: string; task: string; screened_by: Ref; outcome: string; hazards: string; people_required: number; disputed_at_screen: boolean; valid_until: string; notes: string; created_at: string };
export type Party = { id: string; role: string; name: string; person: string | null; organisation_name: string; status: string; removed_reason: string; national_id_check: string | null; check: { result: string; channel: string; reference: string; checked_at: string | null } | null; created_at: string };
export type SearchRequest = {
  id: string; case: string; task: string; registry: string | null; channel: string; tenmina_account_ref: string; submitted_by: Ref; submitted_at: string;
  registry_reference: string; search_on: string; result_evidence: string | null; result_received_by: Ref; result_received_at: string | null;
  registry_result_date: string | null; result_summary: string; confirmed_by: Ref; confirmed_with: string; confirmed_at: string | null; status: string; rejected_reason: string; usable: boolean;
};
export type Cost = { id: string; item_type: string; amount: MoneyT; incurred_on: string; description: string; source: string };
export type Candidates = {
  task_id: string; owner_role: string; site_visit: boolean; disputed: boolean; people_required: number; visit_blockers: Reason[];
  people: { id: string; name: string; roles: string[]; can_be_main: boolean; can_be_second: boolean; licence: { role: string; valid: boolean; number: string; expires_on: string | null; message: string } | null }[];
};

export type Approval = { id: string; subject_type: string; subject_id: string; prepared_by: string; required: number; status: string; summary: string; created_at: string; closed_at: string | null; approvals: { approver: string; approver_name: string; decision: string; slot: string; at: string }[]; dedicated?: boolean };

export type Instruction = {
  id: string; escrow: string; escrow_reference: string; kind: string; subject_type: string | null; subject_label: string; payee: string | null; payee_name: string;
  payee_account_last4: string; money: MoneyT; amount: string; currency: string; holdback_amount: string; to_currency: string | null; fx_quote: string | null;
  prepared_by: string; reason: string; status: string; client_approved_at: string | null; client_approval_method: string; release_part: string;
  approvals: { slot: string; approver: string; decision: string; at: string }[]; clock: import('./kit').Clock; document_sha256: string; sent_at: string | null;
  sent_channel: string; sent_reference: string; last_send_error: string; shortfall_amount: string | null; refund_source_event: string | null; refund_change: string | null;
  bank_confirmation_event: string | null; closed_reason: string; blocking_reasons: Reason[]; row_version: number; created_at: string;
};

export type EscrowRow = { id: string; reference: string; kind: string; title: string; country: string; client: string; status: string; agreed_price: MoneyT; currency: string; created_at: string };
export type Escrow = EscrowRow & {
  asset_id: string | null; report_id: string | null; project_id: string | null; case_id: string | null; bank_partner: string | null; bank_reference: string;
  virtual_account_ref: string; held_back_amount: string; held_back_condition: string; conversion_choice: string; fx_buffer_pct: string | null; terms_version: string | null;
  prior_status: string; fresh_search_case_id: string | null; fresh_search_result_date: string | null; site_check_date: string | null; agreed_at: string | null;
  funded_at: string | null; closed_at: string | null; cancel_requested_at: string | null; cancel_reason: string;
  parties: { id: string; role: string; person: string | null; organisation: string | null; name: string; payee: string | null; national_id_check: string | null; must_accept: boolean; accepted_current_terms: boolean }[];
  conditions: { id: string; key: string; text: string; status: string; release_part: string; closed_by: string | null; closed_at: string | null; closed_note: string; reopened_at: string | null; reopen_reason: string }[];
  funds: Record<string, string | null>[]; payment_instructions: Record<string, unknown>; agreement_blockers: Reason[];
  freezes: { id: string; kind: string; reason: string; frozen_at: string; lifted_at: string | null }[]; row_version: number;
};

export type BankEvent = {
  id: string; escrow: string | null; kind: string; amount: string; currency: string; occurred_at: string; bank_reference: string; virtual_account_ref: string | null;
  source: string; status: string; proof_evidence: string | null; entered_by: string | null; checked_by: string | null; checked_at: string | null;
  source_bank_name: string; source_account_name: string; source_account_last4: string; deposit_route: string; misdirected: boolean; note: string; created_at: string;
};

export type Payee = {
  id: string; country: string; kind: string; subject_type: string; subject_id: string; legal_name: string; bank_name: string; account_name: string; account_last4: string;
  account_name_source: string; name_match: string; verification_status: string; prepared_by: string | null; verified_by: string | null; second_check_by: string | null;
  verified_at: string | null; valid_until: string | null; suspend_reason: string; national_id_check: string | null; account_version: number; cooling_off_until: string | null;
  contact_email: string; contact_phone: string; created_at: string;
};

export type PayeeChange = {
  id: string; country: string; kind: string; payee: string | null; replaces_payee: string | null; escrow: string | null; deposit_event: string | null; reason: string;
  request_source: string; bank_name: string; account_name: string; account_last4: string; account_name_source: string; account_checked_by: string | null;
  previous_last4: string; previous_account_name: string; national_id_check: string | null; client_approved_at: string | null; approval_request: string | null;
  applied_at: string | null; cooling_off_until: string | null; stopped_at: string | null; stop_reason: string; requested_by: string; requested_at: string; status: string;
};

export type Report = {
  id: string; reference: string; case: string; case_reference: string; version: number; status: string; overall_verdict: string | null; template_version_number: number;
  scope_version: number | null; submitted_at: string | null; released_at: string | null; pdf_sha256: string; supersedes: string | null; correction_reason: string; release_error: string; created_at: string;
};
export type Signature = { id: string; role: string; signer: string; signer_name: string; licence_number: string; licence_body: string; signed_at: string; content_sha256: string; invalidated_at: string | null; invalidated_reason: string; valid: boolean };
export type Section = {
  id: string; number: number; label: string; position: number; key: string; title: string; owner_role: string; locked: boolean; in_verdict_rule: boolean; needs_signature: boolean;
  findings: Record<string, unknown>; verdict: string | null; proposed_verdict: string | null; proposed_reasons: unknown; edited_at: string | null; signatures: Signature[]; can_edit: boolean;
};
export type ReportDetail = Report & {
  sections: Section[]; conditions: { id: string; position: number; key: string; text: string; responsible: string; closing_evidence: string; release_part: string }[];
  allowed_verdicts: { allowed: string[]; reasons: (string | Reason)[] }; approvals: { slot: string; approver: string; decision: string; at: string }[];
};

export type Page<T> = { items: T[]; next_cursor: string | null };
export type Asset = { id: string; reference: string; type: string; name: string; country: string; owner: string | null; owner_name: string; region: string; district: string; locality: string; address: string; plot_number: string; site_plan_ref: string; ghana_post_gps: string; location: number[] | null; location_source: string; current_boundary: { id: string; version: number; source: string; area_sqm: string; area_acres: string; perimeter_m: string; created_at: string } | null; disputed_flag: boolean; disputed_reason: string; verified_at: string | null; listed_at: string | null; monitoring_active: boolean; open_alerts: number; created_at: string };
