/* Server-side reads for public pages, so listings render without JavaScript and search engines see them
   (US-LST-010). Talks to the API directly, not through the browser's /v1 proxy. */
const API = process.env.TENMINA_API_URL || 'http://localhost:8000';

export async function apiGet<T>(path: string, query?: Record<string, string | undefined>): Promise<{ data?: T; status: number }> {
  const qs = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v) as [string, string][]).toString() : '';
  try {
    const res = await fetch(`${API}${path}${qs ? `?${qs}` : ''}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!res.ok) return { status: res.status };
    return { data: (await res.json()) as T, status: res.status };
  } catch {
    return { status: 503 };
  }
}

export function money(m?: { amount: string; currency: string } | null): string {
  if (!m) return '—';
  try {
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency: m.currency, maximumFractionDigits: 0 }).format(Number(m.amount));
  } catch {
    return `${m.currency} ${m.amount}`;
  }
}

export function day(s?: string | null): string {
  return s ? new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—';
}
