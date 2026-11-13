import type { Href } from 'expo-router';
import type { ApiMoney } from '@tenmina/mobile';
import type { IconName } from '@tenmina/ui';

/** One row of GET /v1/home: everything the client has, from every module (F-35, SCR-PTL-36). */
export interface HomeItem {
  kind: string;
  id: string;
  title: string;
  status: string;
  status_text: string;
  next_date: string | null;
  needs_action: boolean;
  link: string;
  family_member_id: string | null;
  line: string;
  amount: ApiMoney | null;
}

export interface FamilyMember {
  id: string;
  full_name: string;
  relationship: string;
  phone: string;
  address: string;
  may_confirm_visits: boolean;
  country: string;
  status: string;
}

export interface Home {
  person: { full_name: string; home_country: string; residence_country: string; mfa_enabled: boolean };
  family_members: FamilyMember[];
  items: HomeItem[];
  needs_action_count: number;
}

/** Lines shown on each tab. The tabs match the signed-in portal (03 section 2.4). */
export const TAB_LINES = {
  property: ['property', 'escrow', 'listings', 'pmg'],
  family: ['fee', 'care', 'errands', 'ins', 'evt', 'family'],
  projects: ['construction', 'funds', 'pmg', 'disputes'],
} as const;

const ROUTES: [RegExp, (id: string) => string][] = [
  [/^\/cases\/([^/?]+)$/, (id) => `/case/${id}`],
  [/^\/reports\/([^/?]+)$/, (id) => `/report/${id}`],
  [/^\/escrows\/([^/?]+)$/, (id) => `/escrow/${id}`],
  [/^\/release-instructions\/([^/?]+)$/, (id) => `/release/${id}`],
  [/^\/invoices\/([^/?]+)$/, (id) => `/invoice/${id}`],
  [/^\/fee-payments\/([^/?]+)$/, (id) => `/fee-payment/${id}`],
  [/^\/projects\/([^/?]+)$/, (id) => `/project/${id}`],
  [/^\/properties\/([^/?]+)$/, (id) => `/managed/${id}`],
  [/^\/repairs\/([^/?]+)$/, (id) => `/repair/${id}`],
  [/^\/care\/plans\/([^/?]+)$/, (id) => `/care-plan/${id}`],
  [/^\/care\/visits\/([^/?]+)$/, (id) => `/care-visit/${id}`],
  [/^\/care\/concerns\/([^/?]+)$/, (id) => `/concern/${id}`],
  [/^\/errands\/([^/?]+)$/, (id) => `/errand/${id}`],
  [/^\/events\/([^/?]+)$/, (id) => `/event/${id}`],
  [/^\/insurance\/policies\/([^/?]+)$/, (id) => `/policy/${id}`],
  [/^\/insurance\/premiums\/([^/?]+)$/, (id) => `/premium/${id}`],
  [/^\/disputes\/([^/?]+)$/, (id) => `/dispute/${id}`],
  [/^\/payee-changes\/([^/?]+)$/, (id) => `/payee-change/${id}`],
];

/**
 * The app screen for a link the API gives (GET /v1/home, notifications). A
 * link the app has no screen for opens a summary with a link to the website.
 * Opening a link never approves anything (03 section 2.3a).
 */
export function routeFor(link: string, title?: string, detail?: string): Href {
  const path = link.split('?')[0];
  for (const [re, to] of ROUTES) {
    const m = path.match(re);
    if (m) return to(m[1]) as Href;
  }
  return { pathname: '/item', params: { link, title: title ?? '', detail: detail ?? '' } };
}

export function iconFor(kind: string): IconName {
  if (/case|report|partner_order/.test(kind)) return 'document-text-outline';
  if (/escrow|held_funds|release/.test(kind)) return 'lock-closed-outline';
  if (/fee_invoice|fee_payment|fee_schedule|institution/.test(kind)) return 'receipt-outline';
  if (/care/.test(kind)) return 'heart-outline';
  if (/errand/.test(kind)) return 'briefcase-outline';
  if (/event/.test(kind)) return 'calendar-outline';
  if (/ins_/.test(kind)) return 'umbrella-outline';
  if (/project/.test(kind)) return 'construct-outline';
  if (/managed_property|repair/.test(kind)) return 'home-outline';
  if (/dispute/.test(kind)) return 'chatbubbles-outline';
  if (/listing|reservation|enquiry/.test(kind)) return 'map-outline';
  if (/rating/.test(kind)) return 'star-outline';
  if (/bank_account/.test(kind)) return 'card-outline';
  if (/representative/.test(kind)) return 'people-outline';
  return 'ellipse-outline';
}

/** Release instruction (GET /v1/release-instructions/{id}). */
export interface Instruction {
  id: string;
  escrow: string;
  escrow_reference: string;
  kind: string;
  subject_type: string;
  subject_id: string;
  subject_label: string;
  family_member_id: string | null;
  payee: string;
  payee_name: string;
  payee_account_last4: string;
  money: ApiMoney;
  amount: string;
  currency: string;
  holdback_amount: string;
  reason: string;
  status: string;
  client_approved_at: string | null;
  approvals: { approver_name?: string; decision?: string; at?: string }[];
  blocking_reasons: { rule: string; message: string }[];
  created_at: string;
}

export interface Escrow {
  id: string;
  reference: string;
  kind: string;
  title: string;
  country: string;
  status: string;
  agreed_price: ApiMoney;
  currency: string;
  bank_reference: string;
  virtual_account_ref: string;
  held_back_amount: string;
  held_back_condition: string;
  fresh_search_result_date: string | null;
  case_id: string | null;
  report_id: string | null;
  project_id: string | null;
  funded_at: string | null;
  parties: { id: string; role: string; name: string; must_accept: boolean; accepted_current_terms: boolean }[];
  conditions: { id: string; key: string; text: string; status: string; closed_at: string | null; closed_note: string }[];
  funds: { currency: string; virtual_account_ref: string; held_at_bank: string; instructed_awaiting_bank: string; available_to_instruct: string }[];
  payment_instructions: {
    available: boolean;
    bank_name: string;
    account_name: string;
    account_number: string;
    virtual_account_ref: string;
    reference: string;
    currency: string;
    note: string;
  } | null;
  agreement_blockers: { rule?: string; message: string }[] | string[];
  freezes: { reason?: string; kind?: string }[];
}

export const ESCROW_STATUS: Record<string, string> = {
  proposed: 'Proposed',
  agreed: 'Agreed, waiting for money',
  funded: 'Money at the bank',
  ready_to_release: 'Ready to release',
  partly_released: 'Partly released',
  released: 'Released',
  frozen: 'On hold',
  cancelled: 'Cancelled',
  disputed: 'In dispute',
};
