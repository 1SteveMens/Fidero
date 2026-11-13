/* The gates on a release or refund approval (W-15). The API returns only what blocks the instruction
 * (escrow/blockers.py); every gate that returns nothing has passed. Each gate collects its reasons by code or rule. */
import type { Escrow, Instruction, Reason } from '../types';

export type GateRow = { key: string; title: string; ok: boolean; reasons: Reason[]; rule: string };

type Def = { key: string; title: string; rule: string; match: (r: Reason) => boolean; when?: (i: Instruction, e?: Escrow) => boolean };

const RELEASE = (i: Instruction) => i.kind === 'release' || i.kind === 'partial_release';

const DEFS: Def[] = [
  { key: 'paused', title: 'Instructions are not paused', rule: 'ADM', match: (r) => r.code === 'instructions-paused' },
  { key: 'conditions', title: 'All conditions closed with evidence', rule: 'RUL-06', match: (r) => r.code === 'condition-open' || r.code === 'main-release-first', when: RELEASE },
  { key: 'client', title: 'Client approved; silence is never approval', rule: 'RUL-11', match: (r) => r.rule === 'RUL-11', when: (i) => i.kind !== 'cancel_refund' },
  { key: 'fresh', title: 'Fresh search and site check inside the window', rule: 'RUL-07', match: (r) => r.rule === 'RUL-07', when: (i, e) => RELEASE(i) && !!e && ['purchase', 'offplan'].includes(e.kind) },
  { key: 'freeze', title: 'No open dispute, incident or hold', rule: 'RUL-15', match: (r) => r.code === 'escrow-frozen' || r.code === 'escrow-cancelling' },
  { key: 'balance', title: "Within this escrow's confirmed balance at the bank", rule: 'RUL-34', match: (r) => ['virtual-account-missing', 'held-funds-insufficient', 'bank-position-mismatch', 'escrow-not-funded', 'escrow-closed', 'misdirected-deposit'].includes(r.code ?? '') },
  { key: 'fx', title: 'Converted amount covers the price at the accepted quote', rule: 'RUL-35', match: (r) => (r.code ?? '').startsWith('fx-') || r.rule === 'RUL-36', when: (i, e) => !!i.to_currency || !!i.fx_quote || i.kind === 'conversion' || e?.conversion_choice === 'at_release' },
  { key: 'payee', title: 'Payee verified, the bank matched the account name, payee locked and not in cooling-off', rule: 'RUL-22, RUL-28', match: (r) => (r.code ?? '').startsWith('payee-'), when: RELEASE },
  { key: 'identity', title: "Payee's identity checked with the national identity system", rule: 'RUL-31', match: (r) => r.rule === 'RUL-31', when: RELEASE },
  { key: 'refund', title: 'Refund goes to the source account', rule: 'RUL-29', match: (r) => (r.code ?? '').startsWith('refund-'), when: (i) => i.kind === 'cancel_refund' },
];

export function gates(i: Instruction, e?: Escrow): GateRow[] {
  const reasons = (i.blocking_reasons ?? []).filter((r) => r.code !== 'staff-approvals-missing');
  const used = new Set<Reason>();
  const rows: GateRow[] = [];
  for (const d of DEFS) {
    const mine = reasons.filter((r) => d.match(r));
    mine.forEach((r) => used.add(r));
    if (d.when && !d.when(i, e) && !mine.length) continue;
    if (d.key === 'paused' && !mine.length) continue;
    rows.push({ key: d.key, title: d.title, ok: mine.length === 0, reasons: mine, rule: d.rule });
  }
  const rest = reasons.filter((r) => !used.has(r));
  rows.push({ key: 'subject', title: i.subject_label ? `Checks for ${i.subject_label}` : 'Checks for what is being paid', ok: rest.length === 0, reasons: rest, rule: rest[0]?.rule ?? '' });
  return rows;
}
