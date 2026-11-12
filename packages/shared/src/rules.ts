// Client-side views of business rules from docs/specs/01 section B7.
// They decide what the app shows and enables. The server enforces the same
// rules again and is the authority: nothing here moves money.

import type { Escrow, Invoice, ReportSection, Verdict } from './types';

/** RUL-02: the overall verdict cannot be green if any section from 4 to 10 is red. */
export function allowedOverallVerdicts(sections: ReportSection[]): Verdict[] {
  const anyRed = sections.some((s) => s.number >= 4 && s.number <= 10 && s.verdict === 'red');
  return anyRed ? ['amber', 'red'] : ['green', 'amber', 'red'];
}

/** Whole days from one ISO date to another, by calendar date only. */
export function daysBetween(fromIso: string, toIso: string): number {
  const toUtc = (iso: string) => {
    const [y, m, d] = iso.split('-').map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((toUtc(toIso) - toUtc(fromIso)) / 86_400_000);
}

export interface ReleaseCheckOptions {
  todayIso: string;
  /** The configured fresh-search window (FR-ADM-005). [TO VERIFY] per Q-04. */
  freshSearchWindowDays: number;
}

/**
 * Reasons a client may not approve this release yet (RUL-06, RUL-07, RUL-15,
 * FR-ESC-006, FR-ESC-015). An empty list means the client may approve.
 */
export function releaseBlockers(escrow: Escrow, opts: ReleaseCheckOptions): string[] {
  const reasons: string[] = [];
  const open = escrow.conditions.filter((c) => !c.closedOn).length;
  if (open > 0) reasons.push(`${open} condition${open === 1 ? '' : 's'} still open`);
  if (escrow.freshSearchRequired) {
    if (!escrow.freshSearchOn) {
      reasons.push('The fresh search has not been done');
    } else if (daysBetween(escrow.freshSearchOn, opts.todayIso) > opts.freshSearchWindowDays) {
      reasons.push('The fresh search is out of date');
    }
  }
  if (escrow.disputeOpen) reasons.push('A dispute is open, so payments are frozen');
  if (escrow.payee.nameCheck !== 'matched') {
    reasons.push("The bank has not confirmed the payee's account name");
  }
  if (escrow.status !== 'ready_to_release') reasons.push('This release is not waiting for your approval');
  return reasons;
}

/** Reasons an invoice may not be approved yet (RUL-22, FR-FEE-002, FR-FEE-003). */
export function invoiceBlockers(invoice: Invoice): string[] {
  const reasons: string[] = [];
  if (!invoice.institutionVerified) reasons.push('The institution is not verified');
  if (invoice.payee.nameCheck !== 'matched') {
    reasons.push("The bank has not confirmed the institution's account name");
  }
  for (const check of invoice.checks) {
    if (!check.ok) reasons.push(`Check failed: ${check.label}`);
  }
  if (invoice.status !== 'awaiting_client') reasons.push('This invoice is not waiting for your approval');
  return reasons;
}

/** A second factor is a 6-digit code from an authenticator app (FR-ACC-003). */
export function isWellFormedCode(code: string): boolean {
  return /^\d{6}$/.test(code);
}

/** The three steps every release goes through (RUL-05, RUL-11). */
export const RELEASE_STEPS = ['You approve', 'Two Tenmina staff approve', 'The bank pays'] as const;
