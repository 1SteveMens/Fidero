import type { Money as MoneyT } from '@tenmina/api-client';

export type Period = { id: string; period_start: string; due_on: string; expected: MoneyT; received: MoneyT | null; received_on: string | null; status: string; status_text: string };
export type Tenancy = {
  id: string; property: string; property_title: string; agreement_evidence: string | null; rent: MoneyT; period: string; due_day: number; starts_on: string; ends_on: string | null;
  tenant_reference: string; status: string; payment_details: { account_holder: string; bank_name: string; account_name: string; account_number: string; reference: string; amount: MoneyT; note: string } | null; periods: Period[];
};

