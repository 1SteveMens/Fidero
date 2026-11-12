// Domain types shared by the Fidero apps. Names follow docs/specs/01 and 02.

export type CountryCode = 'GH' | 'NG' | 'KE';

export type Currency = 'GHS' | 'NGN' | 'KES' | 'USD' | 'GBP' | 'EUR' | 'CAD';

/** Money in minor units (pesewas, kobo, cents) so sums never drift. */
export interface Money {
  amountMinor: number;
  currency: Currency;
}

export type Verdict = 'green' | 'amber' | 'red';

export type PayeeKind =
  | 'institution'
  | 'seller'
  | 'developer'
  | 'contractor'
  | 'carer'
  | 'supplier'
  | 'vendor'
  | 'agency';

/** A verified payee (RUL-22). The bank's name check must match before any release (FR-ESC-015). */
export interface Payee {
  id: string;
  kind: PayeeKind;
  name: string;
  bankName: string;
  accountLast4: string;
  nameCheck: 'matched' | 'mismatch' | 'pending';
}

export type StepState = 'done' | 'current' | 'upcoming';

export interface CaseStep {
  id: string;
  title: string;
  detail?: string;
  state: StepState;
}

export type CaseStatus = 'paid' | 'in_progress' | 'on_hold' | 'in_review' | 'released' | 'cancelled';

export interface Case {
  id: string;
  ref: string;
  country: CountryCode;
  line: 'land' | 'building';
  title: string;
  status: CaseStatus;
  next?: { title: string; detail: string };
  steps: CaseStep[];
  reportId?: string;
  escrowId?: string;
  /** Overall verdict once the report is released. */
  verdict?: Verdict;
}

export interface ReportSection {
  /** Section number in the report template (4 to 10 carry verdicts). */
  number: number;
  title: string;
  verdict: Verdict;
}

export interface Report {
  id: string;
  caseId: string;
  releasedOn: string;
  version: number;
  verdict: Verdict;
  headline: string;
  mustHappen: string[];
  sections: ReportSection[];
  signedBy: string;
  /** SHA-256 of the released PDF, shown shortened (FR-RPT-007). */
  fingerprint: string;
}

export interface Condition {
  id: string;
  text: string;
  closedOn?: string;
}

export type EscrowStatus =
  | 'proposed'
  | 'agreed'
  | 'funded'
  | 'ready_to_release'
  | 'client_approved'
  | 'release_approved'
  | 'partly_released'
  | 'released'
  | 'frozen'
  | 'cancelled';

export interface Escrow {
  id: string;
  bankRef: string;
  caseId: string;
  title: string;
  heldAt: string;
  heldSince: string;
  held: Money;
  /** The release the client is asked to approve. */
  release: Money;
  payee: Payee;
  status: EscrowStatus;
  conditions: Condition[];
  /** Purchases need a fresh search before release (RUL-07); fees, care and errands do not. */
  freshSearchRequired: boolean;
  freshSearchOn?: string;
  disputeOpen: boolean;
}

export interface InvoiceCheck {
  label: string;
  ok: boolean;
}

export type InvoiceStatus = 'awaiting_client' | 'awaiting_staff' | 'paid' | 'disputed';

export interface Invoice {
  id: string;
  ref: string;
  issuedOn: string;
  description: string;
  familyMember: string;
  institutionPlace: string;
  institutionVerified: boolean;
  payee: Payee;
  amount: Money;
  checks: InvoiceCheck[];
  status: InvoiceStatus;
  receiptExpected: string;
}

export interface NeedsYouItem {
  id: string;
  title: string;
  detail: string;
  /** App route to open, for example `/escrow/esc-2207`. */
  href: string;
}

export interface HomeRow {
  id: string;
  title: string;
  detail: string;
  href?: string;
  badge?: { label: string; verdict?: Verdict };
}

/** One account the bank holds for the client. Fidero never holds it (RUL-01). */
export interface HeldAccount {
  id: string;
  /** What the money is for, for example "Plot 14, Kasoa". */
  label: string;
  kind: 'escrow' | 'family';
  bankRef: string;
  heldAt: string;
  held: Money;
  href: string;
}

export interface Dashboard {
  firstName: string;
  /** As the bank holds it, shown on the account cards. */
  fullName: string;
  country: CountryCode;
  currency: Currency;
  /** Sum of all accounts. */
  held: Money;
  heldAt: string;
  accounts: HeldAccount[];
  needsYou: NeedsYouItem[];
  property: HomeRow[];
  family: HomeRow[];
  projects: HomeRow[];
}

export interface FamilyMember {
  id: string;
  name: string;
  relationship: string;
  place: string;
  rows: HomeRow[];
}

export interface Errand {
  id: string;
  title: string;
  agency: string;
  step: number;
  steps: number;
  /** Short names for each step, as many as steps. */
  stepLabels: string[];
  status: string;
}

export interface DeletionPreview {
  deletedNow: string[];
  keptAndWhy: { item: string; why: string }[];
  blockedBy: string[];
}

export interface ApprovalResult {
  ok: boolean;
  message: string;
}
