import { useGet } from './hooks';
import { useSession } from './session';

/** A country as GET /v1/countries gives it. Country is configuration: no screen names Ghana or its currency. */
export interface CountryInfo {
  code: string;
  name: string;
  currency: string;
  phone_prefix: string;
  /** What the country's digital address is called ("Ghana Post GPS address") and an example; null if none. */
  digital_address: { name: string; example: string } | null;
  national_id_name: string;
  land_registry_name: string;
}

/**
 * A country's name, currency and wording from configuration: the code given (an object's own country), else
 * the signed-in person's home country. Empty strings until it has loaded.
 */
export function useCountry(code?: string | null): CountryInfo {
  const { me } = useSession();
  const q = useGet<CountryInfo[]>('/v1/countries');
  const want = code || me?.home_country || '';
  const c = (q.data ?? []).find((x) => x.code === want);
  return {
    code: want, name: c?.name ?? want, currency: c?.currency ?? '', phone_prefix: c?.phone_prefix ?? '',
    digital_address: c?.digital_address ?? null, national_id_name: c?.national_id_name ?? '',
    land_registry_name: c?.land_registry_name ?? '',
  };
}

/** The label for a country's digital address field. */
export function addressLabel(c: CountryInfo): string {
  return c.digital_address?.name || 'Digital address';
}
