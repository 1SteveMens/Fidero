// Sample data for building and demonstrating the apps before the API exists.
// Every name, amount, reference and date here is invented sample data.

import type { FideroApi } from './api';
import { isWellFormedCode, releaseBlockers, invoiceBlockers } from './rules';
import type {
  Case,
  Dashboard,
  DeletionPreview,
  Errand,
  Escrow,
  FamilyMember,
  Invoice,
  Payee,
  Report,
} from './types';

/** The sample world's "today", so the demo never depends on the device clock. */
export const SAMPLE_TODAY = '2027-04-03';
export const SAMPLE_FRESH_SEARCH_WINDOW_DAYS = 14;

const sellerPayee: Payee = {
  id: 'pay-nii-ayi',
  kind: 'seller',
  name: 'Nii Ayi Family Trust',
  bankName: 'Partner Bank',
  accountLast4: '3318',
  nameCheck: 'matched',
};

const hospitalPayee: Payee = {
  id: 'pay-kath',
  kind: 'institution',
  name: 'Komfo Anokye Teaching Hospital',
  bankName: 'Partner Bank',
  accountLast4: '4471',
  nameCheck: 'matched',
};

const cases: Case[] = [
  {
    id: 'case-0142',
    ref: 'FID-GH-2027-0142',
    country: 'GH',
    line: 'land',
    title: 'Plot 14, Kasoa Millennium City',
    status: 'released',
    next: {
      title: 'Approve the release to the seller.',
      detail: 'All 5 conditions are closed and the fresh search was done on 2 April.',
    },
    steps: [
      { id: 's1', title: 'Paid and accepted', detail: '3 March', state: 'done' },
      { id: 's2', title: 'Searches lodged at the Lands Commission', detail: '5 March', state: 'done' },
      { id: 's3', title: 'Surveyor visited the plot', detail: '9 March. 3 of 4 pillars found. 12 photos.', state: 'done' },
      { id: 's4', title: 'Map checks clear', detail: 'Not in an acquisition, road reserve, wetland or flood zone.', state: 'done' },
      { id: 's5', title: "Seller's right to sell", detail: 'Consent signed and filmed on 14 March.', state: 'done' },
      { id: 's6', title: 'Legal review and second review', detail: '31 March', state: 'done' },
      { id: 's7', title: 'Report released', detail: '1 April. Amber.', state: 'done' },
      { id: 's8', title: 'Escrow', detail: 'Ready for your approval', state: 'current' },
    ],
    reportId: 'rep-0142',
    escrowId: 'esc-2207',
  },
  {
    id: 'case-0150',
    ref: 'FID-GH-2027-0150',
    country: 'GH',
    line: 'building',
    title: 'House, East Legon',
    status: 'in_progress',
    next: {
      title: 'Structural inspection on 8 April.',
      detail: 'Kofi Nyarko, building inspector, visits with a runner.',
    },
    steps: [
      { id: 's1', title: 'Paid and accepted', detail: '28 March', state: 'done' },
      { id: 's2', title: 'Searches lodged at the Lands Commission', detail: '30 March', state: 'done' },
      { id: 's3', title: 'Structural inspection', detail: 'Booked for 8 April', state: 'current' },
      { id: 's4', title: 'Occupants, rates and utility bills', state: 'upcoming' },
      { id: 's5', title: 'Legal review and second review', state: 'upcoming' },
      { id: 's6', title: 'Your report', detail: 'Expected by 25 April', state: 'upcoming' },
    ],
  },
];

const reports: Report[] = [
  {
    id: 'rep-0142',
    caseId: 'case-0142',
    releasedOn: '2027-04-01',
    version: 1,
    verdict: 'amber',
    headline: 'Do not pay yet. Two things must happen first.',
    mustHappen: [
      'The family head signs the consent on film, with two witnesses.',
      'The surveyor replaces the missing north-east pillar.',
    ],
    sections: [
      { number: 4, title: 'Plot matches the site plan', verdict: 'green' },
      { number: 5, title: 'Lands Commission searches', verdict: 'green' },
      { number: 6, title: "Surveyor's check", verdict: 'amber' },
      { number: 7, title: 'Map checks', verdict: 'green' },
      { number: 8, title: "Seller's right to sell", verdict: 'amber' },
      { number: 9, title: 'Chain of ownership', verdict: 'green' },
      { number: 10, title: 'Who is on the land', verdict: 'green' },
    ],
    signedBy: 'Signed by Efua Mensah, lawyer, and Kwame Asante, licensed surveyor. Reviewed by Esi Boateng, Fidero.',
    fingerprint: '9f2c 41d8 … 07be a41e',
  },
];

const escrows: Escrow[] = [
  {
    id: 'esc-2207',
    bankRef: 'PB-ESC-2207',
    caseId: 'case-0142',
    title: 'Plot 14, Kasoa',
    heldAt: 'Partner Bank',
    heldSince: '2027-03-18',
    held: { amountMinor: 8_500_000, currency: 'GHS' },
    release: { amountMinor: 8_500_000, currency: 'GHS' },
    payee: sellerPayee,
    status: 'ready_to_release',
    freshSearchRequired: true,
    freshSearchOn: '2027-04-02',
    disputeOpen: false,
    conditions: [
      { id: 'c1', text: "Family head's consent signed and filmed", closedOn: '2027-03-14' },
      { id: 'c2', text: 'Missing pillar replaced and photographed', closedOn: '2027-03-20' },
      { id: 'c3', text: 'Indenture signed by both sides', closedOn: '2027-04-01' },
      { id: 'c4', text: "Seller's tax clearance", closedOn: '2027-04-01' },
      { id: 'c5', text: 'Fresh search: nothing new on the plot', closedOn: '2027-04-02' },
    ],
  },
];

const invoices: Invoice[] = [
  {
    id: 'inv-55821',
    ref: 'KATH-IP-55821',
    issuedOn: '2027-04-02',
    description: 'Ward stay and medicines, 28 March to 1 April',
    familyMember: 'Akua Mensah',
    institutionPlace: 'Kumasi',
    institutionVerified: true,
    payee: hospitalPayee,
    amount: { amountMinor: 186_000, currency: 'GHS' },
    checks: [
      { label: "Sent by the hospital's finance office", ok: true },
      { label: "Patient matches Mum's details", ok: true },
      { label: "Amount matches the hospital's copy", ok: true },
    ],
    status: 'awaiting_client',
    receiptExpected: 'usually within 2 working days',
  },
];

const family: FamilyMember[] = [
  {
    id: 'fam-akua',
    name: 'Akua Mensah',
    relationship: 'Mum',
    place: 'Ahodwo, Kumasi',
    rows: [
      { id: 'f1', title: 'Hospital bill, Komfo Anokye', detail: 'GHS 1,860.00 waiting for you', href: '/invoice/inv-55821' },
      { id: 'f2', title: 'Care visits', detail: '2 of 2 confirmed this week' },
    ],
  },
  {
    id: 'fam-kofi',
    name: 'Kofi Owusu',
    relationship: 'Nephew',
    place: "St. Mary's School, Kumasi",
    rows: [{ id: 'f3', title: 'Term 3 fees', detail: 'GHS 2,450.00 due 28 April' }],
  },
];

const errands: Errand[] = [
  { id: 'err-1', title: 'Ghana Card renewal', agency: 'National Identification Authority', step: 3, steps: 5, status: 'Lodged. Waiting for the card.' },
];

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function find<T extends { id: string }>(list: T[], id: string, what: string): T {
  const found = list.find((x) => x.id === id);
  if (!found) throw new Error(`${what} not found: ${id}`);
  return clone(found);
}

/** An in-memory API over the sample data. Approvals change state for the session only. */
export function createSampleApi(delayMs = 150): FideroApi {
  const state = {
    escrows: clone(escrows),
    invoices: clone(invoices),
  };
  const wait = <T>(value: T) => new Promise<T>((resolve) => setTimeout(() => resolve(value), delayMs));

  return {
    async getDashboard(): Promise<Dashboard> {
      const escrow = state.escrows[0];
      const invoice = state.invoices[0];
      const needsYou = [
        escrow.status === 'ready_to_release'
          ? { id: 'n1', title: 'Approve the release for Plot 14, Kasoa', detail: 'All 5 conditions closed. Fresh search done 2 April.', href: `/escrow/${escrow.id}` }
          : null,
        invoice.status === 'awaiting_client'
          ? { id: 'n2', title: "Mum's hospital bill", detail: 'GHS 1,860.00 from Komfo Anokye Teaching Hospital', href: `/invoice/${invoice.id}` }
          : null,
      ].filter((x): x is NonNullable<typeof x> => x !== null);
      return wait({
        firstName: 'Ama',
        country: 'GH',
        currency: 'GHS',
        held: { amountMinor: escrow.held.amountMinor + 245_000, currency: 'GHS' },
        heldAt: 'Partner Bank',
        needsYou,
        property: [
          { id: 'p1', title: 'Plot 14, Kasoa Millennium City', detail: escrow.status === 'ready_to_release' ? 'Escrow ready to release' : 'Release approved by you. Fidero staff approving.', href: '/case/case-0142', badge: { label: 'Amber report', verdict: 'amber' } },
          { id: 'p2', title: 'House, East Legon', detail: 'Structural inspection on 8 April', href: '/case/case-0150' },
        ],
        family: [
          { id: 'f1', title: 'Care visits for Mum, Ahodwo', detail: '2 of 2 confirmed' },
          { id: 'f2', title: "Kofi, St. Mary's School", detail: 'Term 3 due 28 April' },
        ],
        projects: [{ id: 'e1', title: 'Ghana Card renewal', detail: 'Lodged · step 3 of 5' }],
      });
    },
    listCases: () => wait(clone(cases)),
    getCase: async (id) => wait(find(cases, id, 'Case')),
    getReport: async (id) => wait(find(reports, id, 'Report')),
    getEscrow: async (id) => wait(find(state.escrows, id, 'Escrow')),
    async approveRelease(escrowId, code) {
      const escrow = state.escrows.find((e) => e.id === escrowId);
      if (!escrow) return wait({ ok: false, message: 'This escrow was not found.' });
      const blockers = releaseBlockers(escrow, { todayIso: SAMPLE_TODAY, freshSearchWindowDays: SAMPLE_FRESH_SEARCH_WINDOW_DAYS });
      if (blockers.length > 0) return wait({ ok: false, message: blockers[0] });
      if (!isWellFormedCode(code)) return wait({ ok: false, message: 'Enter the 6-digit code from your authenticator app.' });
      escrow.status = 'client_approved';
      return wait({ ok: true, message: 'You approved. Two Fidero staff approve next, then the bank pays.' });
    },
    getInvoice: async (id) => wait(find(state.invoices, id, 'Invoice')),
    async approveInvoice(invoiceId, code) {
      const invoice = state.invoices.find((i) => i.id === invoiceId);
      if (!invoice) return wait({ ok: false, message: 'This invoice was not found.' });
      const blockers = invoiceBlockers(invoice);
      if (blockers.length > 0) return wait({ ok: false, message: blockers[0] });
      if (!isWellFormedCode(code)) return wait({ ok: false, message: 'Enter the 6-digit code from your authenticator app.' });
      invoice.status = 'awaiting_staff';
      return wait({ ok: true, message: 'You approved. Two Fidero staff approve next, then the bank pays the hospital.' });
    },
    listFamily: () => wait(clone(family)),
    listErrands: () => wait(clone(errands)),
    previewAccountDeletion: async (): Promise<DeletionPreview> =>
      wait({
        deletedNow: ['Your sign-in, profile and notification settings', 'Your saved family members and institutions'],
        keptAndWhy: [
          { item: 'Released reports and their evidence', why: 'Kept for the period our lawyer and insurer require, then deleted.' },
          { item: 'Escrow and payment records', why: 'Banking and tax law require us to keep them.' },
        ],
        blockedBy: state.escrows.some((e) => !['released', 'cancelled'].includes(e.status))
          ? ['You have money held at the bank for Plot 14, Kasoa. It must be released or refunded first.']
          : [],
      }),
  };
}
