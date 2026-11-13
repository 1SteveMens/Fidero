import { describe, expect, it } from 'vitest';
import { day, initials, money, moneyOf, shortHash, toMinor, words } from '../src/format';

describe('money as the API sends it', () => {
  it('formats decimal strings without rounding', () => {
    expect(money({ amount: '1850.00', currency: 'GHS' })).toBe('GHS 1,850.00');
    expect(money({ amount: '180000', currency: 'GHS' })).toBe('GHS 180,000.00');
    expect(money({ amount: '0.5', currency: 'USD' })).toBe('USD 0.50');
    expect(money({ amount: '12.345', currency: 'GHS' })).toBe('GHS 12.345');
    expect(money({ amount: '-25.00', currency: 'GHS' })).toBe('−GHS 25.00');
    expect(money(null)).toBe('—');
    expect(moneyOf('300', 'GHS')).toBe('GHS 300.00');
  });

  it('converts to minor units for the shared Bloc cards', () => {
    expect(toMinor({ amount: '21500.00', currency: 'GHS' })).toEqual({ amountMinor: 2150000, currency: 'GHS' });
  });
});

describe('words', () => {
  it('turns codes into plain words', () => {
    expect(words('awaiting_client')).toBe('Awaiting client');
    expect(initials('Ama Mensah')).toBe('AM');
    expect(day('2026-11-13')).toBe('13 Nov 2026');
    expect(shortHash('8eb00a2782b5ac4657b9be3310345bcc')).toBe('8eb0 … 5bcc');
  });
});
