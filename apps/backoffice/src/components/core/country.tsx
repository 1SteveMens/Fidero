'use client';
/* The country a staff member is working in (FR-CTY-001: country is configuration). The list comes from their role
 * grants (`work_countries` on /v1/me), each with the currency from the country record. Someone who works in
 * more than one country picks one in the side menu; the choice is remembered in this browser only. */
import { createContext, useContext, useMemo, useState } from 'react';
import { Field, Select, useSession } from '@tenmina/web-ui';

export type WorkCountry = { code: string; name: string; currency: string };
type Ctx = { country: WorkCountry | null; countries: WorkCountry[]; choose: (code: string) => void };

const KEY = 'tenmina.bo.country';
const CountryCtx = createContext<Ctx | null>(null);

function remembered(): string | null {
  if (typeof window === 'undefined') return null;
  try { return window.localStorage.getItem(KEY); } catch { return null; }
}

export function CountryProvider({ children }: { children: React.ReactNode }) {
  const { me } = useSession();
  const countries = useMemo<WorkCountry[]>(() => me?.work_countries ?? [], [me]);
  // Mounted only after the session has loaded in the browser, so reading storage on first render is safe.
  const [chosen, setChosen] = useState<string | null>(remembered);
  const value = useMemo<Ctx>(() => {
    // The chosen country if it is still granted; else home country; else the first granted one.
    const country = countries.find((c) => c.code === chosen)
      ?? countries.find((c) => c.code === me?.home_country)
      ?? countries[0]
      ?? null;
    return {
      country, countries,
      choose: (code) => {
        setChosen(code);
        try { window.localStorage.setItem(KEY, code); } catch { /* private window: keep it for this visit only */ }
      },
    };
  }, [countries, chosen, me?.home_country]);
  return <CountryCtx.Provider value={value}>{children}</CountryCtx.Provider>;
}

/** The working country and its currency. `code` is '' when the person has no staff country. */
export function useWorkCountry(): { code: string; currency: string; name: string; countries: WorkCountry[] } {
  const c = useContext(CountryCtx);
  if (!c) throw new Error('CountryProvider missing');
  return { code: c.country?.code ?? '', currency: c.country?.currency ?? '', name: c.country?.name ?? '', countries: c.countries };
}

/** Currency of a given country code, from the staff member's countries; falls back to the working country's. */
export function useCurrencyOf(code?: string | null): string {
  const c = useContext(CountryCtx);
  if (!c) throw new Error('CountryProvider missing');
  return c.countries.find((x) => x.code === code)?.currency ?? c.country?.currency ?? '';
}

/** "Working in" choice: shown only to someone who works in more than one country. */
export function CountryChoice() {
  const c = useContext(CountryCtx);
  if (!c || c.countries.length < 2) return null;
  return (
    <Field label="Working in">
      <Select value={c.country?.code ?? ''} onChange={(e) => c.choose(e.target.value)}>
        {c.countries.map((x) => <option key={x.code} value={x.code}>{x.name} ({x.currency})</option>)}
      </Select>
    </Field>
  );
}
