/* Types for the institution contact's pages (/institution). */
import type { Money } from '@tenmina/api-client';

export type Institution = {
  id: string; country: string; type: string; legal_name: string; registration_number: string; address: string; status: string; status_text: string;
  eligible_for_direct_payment: boolean; not_eligible_reason: string; verified_at: string | null; invoice_channel: string;
  payee: { account_name: string; account_last4: string; bank_name: string; verification_status: string } | null;
  checklist: { key: string; label: string; done: boolean; detail: string }[];
  contacts: { id: string; name?: string; full_name?: string; role?: string }[];
};
export type FeeInvoice = {
  id: string; institution: { id: string; name: string }; family_member: { id: string; relationship: string } | null;
  institution_reference: string; description: string; amount: Money; due_on: string | null; submitted_by: string; check_status: string;
  contact_confirmed: { name: string; at: string } | null; route: string; status: string; status_text: string; created_at: string;
  payment: { id: string; status: string; route: string } | null; evidence: string | null;
};
export type FeePayment = {
  id: string; invoice: { id: string; institution: string; reference: string }; route: string; amount: Money; status: string;
  client_paid_on: string | null; client_transfer_reference: string; institution_confirmed_at: string | null; paid_at: string | null;
  bank_reference: string; receipt_due_at: string | null; receipt_received_at: string | null; receipt_evidence: string | null;
};
