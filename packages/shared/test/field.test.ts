import { describe, expect, it } from 'vitest';
import {
  checkoutNeedsReason,
  createSampleFieldApi,
  defectHoldback,
  distanceMeters,
  distanceWarning,
  inspectionBlockers,
  missingEvidence,
  type ChecklistItem,
} from '../src';

const site = { name: 'Plot', address: '', location: { lat: 5.5341, lng: -0.4212 }, radiusM: 150 };
const items: ChecklistItem[] = [
  { id: 'a', text: 'A', needsPhoto: true },
  { id: 'b', text: 'B', needsPhoto: false },
];

describe('distance (FR-MOB-003)', () => {
  it('is about 111 km per degree of latitude', () => {
    expect(distanceMeters({ lat: 5, lng: 0 }, { lat: 6, lng: 0 })).toBeGreaterThan(110_000);
    expect(distanceMeters({ lat: 5, lng: 0 }, { lat: 6, lng: 0 })).toBeLessThan(112_000);
  });
  it('warns only outside the radius, and when there is no position', () => {
    expect(distanceWarning(40, site)).toBeNull();
    expect(distanceWarning(410, site)).toBe('410 m from Plot. Say why.');
    expect(distanceWarning(2400, site)).toBe('2.4 km from Plot. Say why.');
    expect(distanceWarning(undefined, site)).toMatch(/No position/);
  });
});

describe('inspection result (FR-MOB-007, RUL-09)', () => {
  it('blocks until every check is answered, photos taken and a result chosen', () => {
    expect(inspectionBlockers(items, {}, {}, undefined, [], '')).toEqual(['2 checks left', 'Choose a result']);
    expect(inspectionBlockers(items, { a: 'yes', b: 'yes' }, {}, 'pass', [], '')).toEqual(['1 photo missing']);
    expect(inspectionBlockers(items, { a: 'yes', b: 'yes' }, { a: 1 }, 'pass', [], '')).toEqual([]);
  });
  it('does not allow a pass with a "No" answer', () => {
    expect(inspectionBlockers(items, { a: 'yes', b: 'no' }, { a: 1 }, 'pass', [], '')).toContain('A "No" answer needs Pass with defects or Fail');
  });
  it('needs a valued defect for pass with defects, and a reason for fail', () => {
    expect(inspectionBlockers(items, { a: 'yes', b: 'no' }, { a: 1 }, 'pass_with_defects', [], '')).toContain('Add the defect and its value');
    const d = [{ id: 'd', itemId: 'b', note: 'cracked', value: { amountMinor: 240_000, currency: 'GHS' as const } }];
    expect(inspectionBlockers(items, { a: 'yes', b: 'no' }, { a: 1 }, 'pass_with_defects', d, '')).toEqual([]);
    expect(inspectionBlockers(items, { a: 'no', b: 'no' }, { a: 1 }, 'fail', [], '')).toContain('Say why it failed');
  });
  it('holds back the sum of the defect values', () => {
    const d = [
      { id: '1', itemId: 'a', note: '', value: { amountMinor: 100_000, currency: 'GHS' as const } },
      { id: '2', itemId: 'b', note: '', value: { amountMinor: 140_000, currency: 'GHS' as const } },
    ];
    expect(defectHoldback(d)).toEqual({ amountMinor: 240_000, currency: 'GHS' });
    expect(defectHoldback([])).toBeNull();
  });
});

describe('milestone evidence (FR-MOB-006) and visits (RUL-23)', () => {
  it('lists evidence items below their minimum', () => {
    const ev = [
      { id: 'x', label: 'X', kind: 'photo' as const, min: 2 },
      { id: 'y', label: 'Y', kind: 'video' as const, min: 1 },
    ];
    expect(missingEvidence(ev, { x: 1, y: 1 }).map((e) => e.id)).toEqual(['x']);
    expect(missingEvidence(ev, { x: 2, y: 1 })).toEqual([]);
  });
  it('counts plan items left at check-out', () => {
    const plan = [{ id: 'p', text: '', needsPhoto: false }, { id: 'q', text: '', needsPhoto: false }];
    expect(checkoutNeedsReason(plan, { p: true })).toBe(1);
  });
});

describe('sample field api', () => {
  it('gives each role its own jobs, and My pay only to professionals (RUL-26 has no verdict field)', async () => {
    const insp = createSampleFieldApi('inspector', 0);
    expect((await insp.listJobs()).every((j) => j.kind === 'inspection')).toBe(true);
    const e = await insp.getEarnings();
    expect(e?.payables.length).toBe(3);
    expect(Object.keys(e!.payables[0])).not.toContain('verdict');
    expect(await createSampleFieldApi('carer', 0).getEarnings()).toBeNull();
    expect((await createSampleFieldApi('contractor', 0).listJobs())[0].kind).toBe('milestone');
  });
});
