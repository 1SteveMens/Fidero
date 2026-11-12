// Tenmina Field: types, rules and sample data for the field app (docs/specs/01 module MOB,
// RUL-08 to RUL-10, RUL-23, RUL-26; docs/specs/03 sections 2.3 and 6.1c).
// Every name, place, coordinate, amount and date in the sample is invented.

import type { Money } from './types';

export type FieldRole = 'inspector' | 'contractor' | 'carer';

export interface FieldUser {
  id: string;
  name: string;
  role: FieldRole;
  /** Shown under the name, for example "Inspector". */
  roleLabel: string;
}

export interface GeoPoint {
  lat: number;
  lng: number;
}

/** A registered place: a plot, a building site or a home for care visits. */
export interface Site {
  name: string;
  address: string;
  location: GeoPoint;
  /** Captures and check-ins further than this from the site are flagged (FR-MOB-003). */
  radiusM: number;
}

export type JobKind = 'inspection' | 'milestone' | 'visit';
export type JobState = 'todo' | 'in_progress' | 'submitted';

export interface FieldJob {
  id: string;
  kind: JobKind;
  ref: string;
  title: string;
  detail: string;
  site: Site;
  /** Local time the job starts, "09:30". */
  startsAt: string;
  endsAt?: string;
  state: JobState;
}

export interface ChecklistItem {
  id: string;
  text: string;
  needsPhoto: boolean;
}

export interface InspectionJob {
  jobId: string;
  project: string;
  milestone: string;
  milestoneNumber: number;
  milestoneCount: number;
  contractor: string;
  /** RUL-10: the inspector has no link to the contractor. */
  conflictChecked: boolean;
  items: ChecklistItem[];
}

export type Answer = 'yes' | 'no';
export type InspectionResult = 'pass' | 'pass_with_defects' | 'fail';

export interface Defect {
  id: string;
  itemId: string;
  note: string;
  value: Money;
}

export interface EvidenceItem {
  id: string;
  label: string;
  kind: 'photo' | 'video';
  /** How many captures the schedule asks for. */
  min: number;
}

export interface MilestoneJob {
  jobId: string;
  project: string;
  name: string;
  number: number;
  count: number;
  evidence: EvidenceItem[];
}

export interface VisitPlanItem {
  id: string;
  text: string;
  needsPhoto: boolean;
}

export interface CareVisitJob {
  jobId: string;
  person: string;
  plan: VisitPlanItem[];
}

/** One capture taken in the app's own camera (RUL-08). */
export interface Capture {
  id: string;
  jobId: string;
  itemId: string;
  kind: 'photo' | 'video';
  uri: string;
  takenAt: string;
  position?: GeoPoint & { accuracyM?: number };
  distanceM?: number;
  /** SHA-256 of the file, taken on the phone at capture (FR-MOB-004, first half). */
  sha256: string;
  /** Why a capture was taken away from the site, when it was (FR-MOB-003). */
  note?: string;
}

export type PayableState = 'in_run' | 'due' | 'held' | 'paid';

/** A professional's payable. Deliberately has no verdict or result field (RUL-26). */
export interface Payable {
  id: string;
  workType: string;
  ref: string;
  acceptedOn: string;
  amount: Money;
  state: PayableState;
  /** Plain words; for held items, never the result of the work. */
  note: string;
}

export interface Earnings {
  monthLabel: string;
  acceptedNotPaid: Money;
  paidThisMonth: Money;
  nextRunOn: string;
  payToLast4: string;
  payables: Payable[];
}

export interface FieldApi {
  me(): Promise<FieldUser>;
  listJobs(): Promise<FieldJob[]>;
  getJob(id: string): Promise<FieldJob>;
  getInspection(jobId: string): Promise<InspectionJob>;
  getMilestone(jobId: string): Promise<MilestoneJob>;
  getVisit(jobId: string): Promise<CareVisitJob>;
  /** Only contracted professionals have My pay. Carers and contractors get null. */
  getEarnings(): Promise<Earnings | null>;
}

/* ---------- Rules ---------- */

/** Great-circle distance in metres between two points. */
export function distanceMeters(a: GeoPoint, b: GeoPoint): number {
  const R = 6371000;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** FR-MOB-003 and FR-MOB-012: a plain-words warning when a capture or check-in is too far from the site. */
export function distanceWarning(distanceM: number | undefined, site: Site): string | null {
  if (distanceM === undefined) return 'No position yet. Wait for GPS, or say why it is missing.';
  if (distanceM <= site.radiusM) return null;
  const shown = distanceM < 1000 ? `${Math.round(distanceM / 10) * 10} m` : `${(distanceM / 1000).toFixed(1)} km`;
  return `${shown} from ${site.name}. Say why.`;
}

/** FR-MOB-007 and RUL-09: what stops an inspection result from being submitted. */
export function inspectionBlockers(
  items: ChecklistItem[],
  answers: Record<string, Answer | undefined>,
  photos: Record<string, number | undefined>,
  result: InspectionResult | undefined,
  defects: Defect[],
  failReason: string,
): string[] {
  const out: string[] = [];
  const unanswered = items.filter((i) => !answers[i.id]).length;
  if (unanswered) out.push(`${unanswered} ${unanswered === 1 ? 'check' : 'checks'} left`);
  const noPhoto = items.filter((i) => i.needsPhoto && answers[i.id] && !(photos[i.id] ?? 0)).length;
  if (noPhoto) out.push(`${noPhoto} ${noPhoto === 1 ? 'photo' : 'photos'} missing`);
  if (!result) out.push('Choose a result');
  const anyNo = items.some((i) => answers[i.id] === 'no');
  if (result === 'pass' && anyNo) out.push('A "No" answer needs Pass with defects or Fail');
  if (result === 'pass_with_defects' && defects.length === 0) out.push('Add the defect and its value');
  if (result === 'pass_with_defects' && defects.some((d) => d.value.amountMinor <= 0)) out.push('Each defect needs a value');
  if (result === 'fail' && failReason.trim().length < 5) out.push('Say why it failed');
  return out;
}

/** RUL-09, FR-BLD-006: the amount held back from the milestone on a pass with defects. */
export function defectHoldback(defects: Defect[]): Money | null {
  if (defects.length === 0) return null;
  return { amountMinor: defects.reduce((n, d) => n + d.value.amountMinor, 0), currency: defects[0].value.currency };
}

/** FR-MOB-006: evidence items that still need captures. */
export function missingEvidence(items: EvidenceItem[], captured: Record<string, number | undefined>): EvidenceItem[] {
  return items.filter((i) => (captured[i.id] ?? 0) < i.min);
}

/** RUL-23, FR-CARE-003: plan items left at check-out need a reason, which the client sees. */
export function checkoutNeedsReason(plan: VisitPlanItem[], done: Record<string, boolean | undefined>): number {
  return plan.filter((p) => !done[p.id]).length;
}

/* ---------- Sample data ---------- */

const KASOA: Site = { name: 'House, Kasoa', address: 'Plot 31, Kasoa New Town', location: { lat: 5.5341, lng: -0.4212 }, radiusM: 150 };
const LEGON: Site = { name: 'House, East Legon', address: '12 Sample Close, East Legon', location: { lat: 5.6372, lng: -0.1541 }, radiusM: 150 };
const TSOPOLI: Site = { name: 'Plot 22, Tsopoli', address: 'Tsopoli, Greater Accra', location: { lat: 5.8301, lng: 0.1204 }, radiusM: 150 };
const AHODWO: Site = { name: 'Comfort Mensah, Ahodwo', address: 'Ahodwo, Kumasi', location: { lat: 6.6681, lng: -1.6293 }, radiusM: 100 };

const USERS: Record<FieldRole, FieldUser> = {
  inspector: { id: 'u-insp', name: 'Yaw Boateng', role: 'inspector', roleLabel: 'Inspector' },
  contractor: { id: 'u-con', name: 'Kwesi Appiah', role: 'contractor', roleLabel: 'Contractor' },
  carer: { id: 'u-care', name: 'Grace Asante', role: 'carer', roleLabel: 'Carer' },
};

const JOBS: Record<FieldRole, FieldJob[]> = {
  inspector: [
    { id: 'job-insp-blocks', kind: 'inspection', ref: 'BLD-2027-0012', title: 'Inspection: Blocks', detail: 'Milestone 3 of 6 · 6 checks', site: KASOA, startsAt: '09:30', state: 'todo' },
    { id: 'job-insp-legon', kind: 'inspection', ref: 'TMN-GH-2027-0150', title: 'Structural inspection', detail: 'Structure, roof and services · 5 checks', site: LEGON, startsAt: '13:00', state: 'todo' },
  ],
  contractor: [
    { id: 'job-ms-foundation', kind: 'milestone', ref: 'BLD-2027-0012', title: 'Foundation', detail: 'Milestone 1 of 6 · 6 evidence items', site: KASOA, startsAt: '08:00', state: 'in_progress' },
  ],
  carer: [
    { id: 'job-visit-comfort', kind: 'visit', ref: 'CARE-2027-0031', title: 'Care visit', detail: 'Plan: 4 items, 2 with photos', site: AHODWO, startsAt: '09:00', endsAt: '10:00', state: 'todo' },
  ],
};

const INSPECTIONS: Record<string, InspectionJob> = {
  'job-insp-blocks': {
    jobId: 'job-insp-blocks', project: 'House, Kasoa', milestone: 'Blocks', milestoneNumber: 3, milestoneCount: 6, contractor: 'Appiah Builders', conflictChecked: true,
    items: [
      { id: 'b1', text: 'Walls match the drawing', needsPhoto: true },
      { id: 'b2', text: 'Walls plumb and level', needsPhoto: true },
      { id: 'b3', text: 'Block quality', needsPhoto: true },
      { id: 'b4', text: 'Mortar joints filled', needsPhoto: false },
      { id: 'b5', text: 'Lintels over openings', needsPhoto: true },
      { id: 'b6', text: 'Site safe and tidy', needsPhoto: false },
    ],
  },
  'job-insp-legon': {
    jobId: 'job-insp-legon', project: 'House, East Legon', milestone: 'Existing building', milestoneNumber: 1, milestoneCount: 1, contractor: 'None: existing building', conflictChecked: true,
    items: [
      { id: 'l1', text: 'No structural cracks in walls or slabs', needsPhoto: true },
      { id: 'l2', text: 'Roof sound, no leaks', needsPhoto: true },
      { id: 'l3', text: 'Electrics: board and earthing', needsPhoto: true },
      { id: 'l4', text: 'Water and drainage working', needsPhoto: false },
      { id: 'l5', text: 'Boundary matches the site plan', needsPhoto: true },
    ],
  },
};

const MILESTONES: Record<string, MilestoneJob> = {
  'job-ms-foundation': {
    jobId: 'job-ms-foundation', project: 'House, Kasoa', name: 'Foundation', number: 1, count: 6,
    evidence: [
      { id: 'f1', label: 'Cleared site, setting out', kind: 'photo', min: 1 },
      { id: 'f2', label: 'Trenches with tape', kind: 'photo', min: 2 },
      { id: 'f3', label: 'Reinforcement, 2 angles', kind: 'photo', min: 2 },
      { id: 'f4', label: 'Video: trench line', kind: 'video', min: 1 },
      { id: 'f5', label: 'Cured foundation', kind: 'photo', min: 1 },
      { id: 'f6', label: 'Delivery notes', kind: 'photo', min: 1 },
    ],
  },
};

const VISITS: Record<string, CareVisitJob> = {
  'job-visit-comfort': {
    jobId: 'job-visit-comfort', person: 'Comfort Mensah',
    plan: [
      { id: 'v1', text: 'Medicines checked', needsPhoto: true },
      { id: 'v2', text: 'Blood pressure reading', needsPhoto: true },
      { id: 'v3', text: 'Companionship, 30 minutes', needsPhoto: false },
      { id: 'v4', text: 'Ask about the next appointment', needsPhoto: false },
    ],
  },
};

const EARNINGS: Earnings = {
  monthLabel: 'May 2027 so far',
  acceptedNotPaid: { amountMinor: 135_000, currency: 'GHS' },
  paidThisMonth: { amountMinor: 210_000, currency: 'GHS' },
  nextRunOn: 'Thursday 27 May',
  payToLast4: '4471',
  payables: [
    { id: 'pay-1', workType: 'Inspection, milestone 2', ref: 'BLD-2027-0012', acceptedOn: '14 May', amount: { amountMinor: 45_000, currency: 'GHS' }, state: 'in_run', note: 'In payment run PAYRUN-GH-2027-014' },
    { id: 'pay-2', workType: 'Structural inspection', ref: 'TMN-GH-2027-0141', acceptedOn: '17 May', amount: { amountMinor: 60_000, currency: 'GHS' }, state: 'due', note: 'Due by 31 May' },
    { id: 'pay-3', workType: 'Site visit', ref: 'TMN-GH-2027-0051', acceptedOn: '20 May', amount: { amountMinor: 30_000, currency: 'GHS' }, state: 'held', note: 'Held: we are checking the evidence on this job. Not about the result.' },
  ],
};

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

/** An in-memory field API for one role, so the founder can test each role's screens. */
export function createSampleFieldApi(role: FieldRole, delayMs = 120): FieldApi {
  const wait = <T>(v: T) => new Promise<T>((r) => setTimeout(() => r(clone(v)), delayMs));
  const find = <T>(map: Record<string, T>, id: string, what: string) => {
    const v = map[id];
    if (!v) throw new Error(`${what} not found: ${id}`);
    return wait(v);
  };
  return {
    me: () => wait(USERS[role]),
    listJobs: () => wait(JOBS[role]),
    getJob: async (id) => {
      const job = JOBS[role].find((j) => j.id === id);
      if (!job) throw new Error(`Job not found: ${id}`);
      return wait(job);
    },
    getInspection: (id) => find(INSPECTIONS, id, 'Inspection'),
    getMilestone: (id) => find(MILESTONES, id, 'Milestone'),
    getVisit: (id) => find(VISITS, id, 'Visit'),
    getEarnings: () => wait(role === 'inspector' ? EARNINGS : null),
  };
}

export const FIELD_ROLES: { role: FieldRole; label: string; detail: string }[] = [
  { role: 'inspector', label: 'Inspector', detail: 'Checklists at building sites, and My pay' },
  { role: 'contractor', label: 'Contractor', detail: 'Milestone evidence, offline' },
  { role: 'carer', label: 'Carer', detail: 'Care visits with check-in and check-out' },
];
