import type { Money, Payee } from './types';

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

function groupThousands(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** "GHS 85,000.00". Written by hand so it renders the same on every engine. */
export function formatMoney(money: Money): string {
  const negative = money.amountMinor < 0;
  const abs = Math.abs(Math.round(money.amountMinor));
  const whole = Math.floor(abs / 100).toString();
  const cents = (abs % 100).toString().padStart(2, '0');
  return `${negative ? '−' : ''}${money.currency} ${groupThousands(whole)}.${cents}`;
}

/** "14 March" from "2027-03-14". Reads the string, never the device clock or time zone. */
export function formatDay(iso: string): string {
  const [, month, day] = iso.split('-').map(Number);
  const name = MONTHS[month - 1];
  if (!name || !day) throw new Error(`Not an ISO date: ${iso}`);
  return `${day} ${name}`;
}

/** The payee line used on every payment (RUL-22): "Paid to X, account ending 4471". */
export function payeeLine(payee: Payee, paid = false): string {
  return `${paid ? 'Paid' : 'To be paid'} to ${payee.name}, account ending ${payee.accountLast4}`;
}

export function verdictWord(verdict: 'green' | 'amber' | 'red'): string {
  return verdict === 'green' ? 'Green' : verdict === 'amber' ? 'Amber' : 'Red';
}
