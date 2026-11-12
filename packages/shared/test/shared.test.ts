import { describe, expect, it } from 'vitest';
import {
  allowedOverallVerdicts,
  createSampleApi,
  daysBetween,
  formatDay,
  formatMoney,
  invoiceBlockers,
  isWellFormedCode,
  payeeLine,
  releaseBlockers,
  type Escrow,
  type Invoice,
} from '../src';

const baseEscrow: Escrow = {
  id: 'e1',
  bankRef: 'PB-1',
  caseId: 'c1',
  title: 'Plot 1',
  heldAt: 'Partner Bank',
  heldSince: '2027-03-01',
  held: { amountMinor: 100_00, currency: 'GHS' },
  release: { amountMinor: 100_00, currency: 'GHS' },
  payee: { id: 'p', kind: 'seller', name: 'Seller', bankName: 'Partner Bank', accountLast4: '1234', nameCheck: 'matched' },
  status: 'ready_to_release',
  conditions: [{ id: 'c', text: 'Consent', closedOn: '2027-03-10' }],
  freshSearchRequired: true,
  freshSearchOn: '2027-04-01',
  disputeOpen: false,
};
const opts = { todayIso: '2027-04-03', freshSearchWindowDays: 14 };

describe('formatMoney', () => {
  it('groups thousands and keeps two decimals', () => {
    expect(formatMoney({ amountMinor: 8_500_000, currency: 'GHS' })).toBe('GHS 85,000.00');
    expect(formatMoney({ amountMinor: 186_005, currency: 'GHS' })).toBe('GHS 1,860.05');
    expect(formatMoney({ amountMinor: 0, currency: 'USD' })).toBe('USD 0.00');
  });
  it('shows negatives with a minus sign', () => {
    expect(formatMoney({ amountMinor: -21_000, currency: 'GHS' })).toBe('−GHS 210.00');
  });
});

describe('formatDay and daysBetween', () => {
  it('reads the date string, not the clock', () => {
    expect(formatDay('2027-03-14')).toBe('14 March');
    expect(() => formatDay('nonsense')).toThrow();
  });
  it('counts calendar days', () => {
    expect(daysBetween('2027-04-01', '2027-04-03')).toBe(2);
    expect(daysBetween('2027-02-28', '2027-03-01')).toBe(1);
  });
});

describe('payeeLine (RUL-22)', () => {
  it('always names the payee and the last four digits', () => {
    expect(payeeLine(baseEscrow.payee, true)).toBe('Paid to Seller, account ending 1234');
  });
});

describe('allowedOverallVerdicts (RUL-02)', () => {
  it('blocks green when any section from 4 to 10 is red', () => {
    expect(allowedOverallVerdicts([{ number: 6, title: 'Survey', verdict: 'red' }])).toEqual(['amber', 'red']);
  });
  it('ignores sections outside 4 to 10', () => {
    expect(allowedOverallVerdicts([{ number: 3, title: 'Scope', verdict: 'red' }])).toContain('green');
  });
});

describe('releaseBlockers', () => {
  it('allows approval when everything is in order', () => {
    expect(releaseBlockers(baseEscrow, opts)).toEqual([]);
  });
  it('blocks open conditions (RUL-06)', () => {
    const e = { ...baseEscrow, conditions: [{ id: 'c', text: 'Consent' }] };
    expect(releaseBlockers(e, opts)).toContain('1 condition still open');
  });
  it('blocks a missing or stale fresh search on purchases (RUL-07)', () => {
    expect(releaseBlockers({ ...baseEscrow, freshSearchOn: undefined }, opts)).toContain('The fresh search has not been done');
    expect(releaseBlockers({ ...baseEscrow, freshSearchOn: '2027-03-01' }, opts)).toContain('The fresh search is out of date');
  });
  it('does not need a fresh search where none is required', () => {
    expect(releaseBlockers({ ...baseEscrow, freshSearchRequired: false, freshSearchOn: undefined }, opts)).toEqual([]);
  });
  it('freezes on an open dispute (RUL-15)', () => {
    expect(releaseBlockers({ ...baseEscrow, disputeOpen: true }, opts)).toContain('A dispute is open, so payments are frozen');
  });
  it('blocks an unconfirmed account name (FR-ESC-015)', () => {
    const e = { ...baseEscrow, payee: { ...baseEscrow.payee, nameCheck: 'mismatch' as const } };
    expect(releaseBlockers(e, opts)).toContain("The bank has not confirmed the payee's account name");
  });
});

describe('invoiceBlockers', () => {
  const inv: Invoice = {
    id: 'i',
    ref: 'R',
    issuedOn: '2027-04-02',
    description: 'd',
    familyMember: 'Mum',
    institutionPlace: 'Kumasi',
    institutionVerified: true,
    payee: { ...baseEscrow.payee, kind: 'institution' },
    amount: { amountMinor: 1000, currency: 'GHS' },
    checks: [{ label: 'Amount matches', ok: true }],
    status: 'awaiting_client',
    receiptExpected: 'soon',
  };
  it('allows a verified institution with passing checks', () => {
    expect(invoiceBlockers(inv)).toEqual([]);
  });
  it('blocks an unverified institution or a failed check', () => {
    expect(invoiceBlockers({ ...inv, institutionVerified: false })).toContain('The institution is not verified');
    expect(invoiceBlockers({ ...inv, checks: [{ label: 'Amount matches', ok: false }] })).toContain('Check failed: Amount matches');
  });
});

describe('isWellFormedCode', () => {
  it('accepts exactly six digits', () => {
    expect(isWellFormedCode('123456')).toBe(true);
    expect(isWellFormedCode('12345')).toBe(false);
    expect(isWellFormedCode('12345a')).toBe(false);
  });
});

describe('sample API', () => {
  it('moves an escrow to client approved, and only with a well-formed code', async () => {
    const api = createSampleApi(0);
    expect((await api.approveRelease('esc-2207', '12')).ok).toBe(false);
    const ok = await api.approveRelease('esc-2207', '123456');
    expect(ok.ok).toBe(true);
    expect((await api.getEscrow('esc-2207')).status).toBe('client_approved');
    expect((await api.approveRelease('esc-2207', '123456')).ok).toBe(false);
  });
  it('blocks account deletion while money is held', async () => {
    const preview = await createSampleApi(0).previewAccountDeletion();
    expect(preview.blockedBy.length).toBeGreaterThan(0);
  });
});
