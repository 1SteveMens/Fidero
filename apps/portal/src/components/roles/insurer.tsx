'use client';
/* Shared pieces for the insurer's pages (/insurer): the policy is the insurer's, Tenmina does not hold the
   risk, premiums go only to the insurer's account, and only the insurer decides claims (RUL-25). */
import type { Money } from '@tenmina/api-client';

export type Application = { id: string; product_name: string; insurer_name: string; insured_family_member: string; answers: Record<string, unknown>; premium_route: string; submitted_to_insurer_at: string | null; insurer_reference: string; insurer_note: string; decided_at: string | null; status: string; status_text: string; policy: string | null; created_at: string };
export type Policy = { id: string; product_name: string; policy_number: string; starts_on: string; renews_on: string; claim_contact: string; premium: Money; premium_period: string; premium_route: string; status: string; status_note: string; document_evidence: string | null };
export type Premium = { id: string; policy_number: string; due_on: string; amount: Money; route: string; client_reported_at: string | null; client_transfer_reference: string; paid_at: string | null; insurer_receipt_evidence: string | null; status: string };
export type Claim = { id: string; policy: string; description: string; event_date: string | null; submitted_to_insurer_at: string | null; insurer_reference: string; insurer_status: string; insurer_status_at: string | null; status_text: string; updates: { id: string; insurer_status: string; note: string; source: string; created_at: string }[]; created_at: string };
export type Product = { id: string; insurer_name: string; kind: string; name: string; summary: string; premium: Money; premium_period: string; premium_routes: string[]; statement: string; status: string; published_at: string | null };

export function InsurerLine() {
  return <div className="banner-info">The policy is yours. Tenmina passes on applications and documents. You decide every application and claim; premiums go only to your account.</div>;
}
