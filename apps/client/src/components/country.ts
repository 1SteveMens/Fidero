import { itemsOf, useGet, useSession } from '@tenmina/mobile';

export { amountOnly } from '../lib';

interface PublicCountry {
  code: string;
  name: string;
  currency: string;
}

/**
 * The signed-in person's home country and its currency, from GET /v1/countries.
 * Country is configuration: nothing about one country is written into the app.
 */
export function useCountry(): { code: string; name: string; currency: string; ready: boolean } {
  const { me } = useSession();
  const q = useGet<{ items: PublicCountry[] } | PublicCountry[]>('/v1/countries');
  const code = me?.home_country || '';
  const c = itemsOf(q.data).find((x) => x.code === code);
  return { code, name: c?.name ?? code, currency: c?.currency ?? '', ready: !!c };
}
