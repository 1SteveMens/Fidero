/** Money as the API sends it: a decimal string and an ISO currency (02 section 7.1). */
export interface ApiMoney {
  amount: string;
  currency: string;
}

/** "GHS 1,850.00", written by hand so it reads the same on every phone. Amounts are never rounded. */
export function money(m: ApiMoney | null | undefined): string {
  if (!m || m.amount === undefined || m.amount === null) return '—';
  const raw = String(m.amount).trim();
  const negative = raw.startsWith('-');
  const [whole, frac = ''] = raw.replace(/^[-+]/, '').split('.');
  if (!/^\d+$/.test(whole || 'x')) return `${m.currency} ${raw}`;
  const cents = (frac + '00').slice(0, Math.max(2, frac.replace(/0+$/, '').length));
  return `${negative ? '−' : ''}${m.currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${cents}`;
}

/** Money from an amount and currency given separately. */
export function moneyOf(amount: string | number | null | undefined, currency: string | null | undefined): string {
  if (amount === null || amount === undefined || !currency) return '—';
  return money({ amount: String(amount), currency });
}

/** For the shared Bloc components, which count in minor units. */
export function toMinor(m: ApiMoney): { amountMinor: number; currency: 'GHS' } {
  return { amountMinor: Math.round(Number(m.amount) * 100), currency: m.currency as 'GHS' };
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "13 Nov 2026" from an ISO date or time. */
export function day(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "13 Nov, 09:30" in the phone's time zone. */
export function when(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** "09:30". */
export function clock(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** A status code as words: "awaiting_client" becomes "Awaiting client". */
export function words(code: string | null | undefined): string {
  if (!code) return '';
  const s = code.replace(/[_-]+/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Two initials from a name, for the black and lime name tiles. */
export function initials(name: string | null | undefined): string {
  return (name ?? '')
    .split(/\s+/)
    .filter((w) => /^[A-Za-z]/.test(w))
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('');
}

/** "4be1 … 9c02": the first and last four characters of a fingerprint. */
export function shortHash(h: string | null | undefined): string {
  if (!h) return '';
  return h.length > 8 ? `${h.slice(0, 4)} … ${h.slice(-4)}` : h;
}
