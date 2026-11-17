import { describe, expect, it } from 'vitest';
import { amountOnly, routeFor, typeFromName } from '../src/lib';

// The client app never sends a person to the website (docs/decisions/2026-11-17-in-app-everything.md):
// every link the API gives opens a screen in the app.
describe('routeFor', () => {
  it('opens listings, orders and family statements in the app', () => {
    expect(routeFor('/listings/abc')).toBe('/listing/abc');
    expect(routeFor('/listings')).toBe('/listings');
    expect(routeFor('/orders/o1/pay')).toBe('/pay-fee/o1');
    expect(routeFor('/orders/o1')).toBe('/pay-fee/o1');
    expect(routeFor('/family/members/m1')).toBe('/member/m1');
    expect(routeFor('/cases/c1/document-requests/r1')).toBe('/case/c1');
  });

  it('keeps the existing screens', () => {
    expect(routeFor('/cases/c1')).toBe('/case/c1');
    expect(routeFor('/reports/r1?x=1')).toBe('/report/r1');
    expect(routeFor('/repairs/r2')).toBe('/repair/r2');
  });

  it('shows anything else as a summary inside the app, never a web page', () => {
    const r = routeFor('/ratings/new', 'Rate the surveyor', 'Tell us how it went');
    expect(r).toEqual({ pathname: '/item', params: { link: '/ratings/new', title: 'Rate the surveyor', detail: 'Tell us how it went' } });
  });
});

describe('amountOnly', () => {
  it('keeps digits and one decimal point with two places', () => {
    expect(amountOnly('GHS 25,000.505')).toBe('25000.50');
    expect(amountOnly('1.2.3')).toBe('1.23');
    expect(amountOnly('abc')).toBe('');
  });
});

describe('typeFromName', () => {
  it('names the types the evidence store accepts', () => {
    expect(typeFromName('Receipt.JPG')).toBe('image/jpeg');
    expect(typeFromName('indenture.pdf')).toBe('application/pdf');
    expect(typeFromName('photo.heic')).toBe('image/heic');
    expect(typeFromName('notes.docx')).toBe('application/octet-stream');
  });
});
