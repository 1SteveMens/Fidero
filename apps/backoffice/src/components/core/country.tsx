'use client';
/* The country a staff member is working in. Country is configuration (CLAUDE.md, DA-09): nothing about
 * Ghana is hard-coded. The choices come from GET /v1/me `work_countries` (the countries the person's role
 * grants cover, home country first); code, name and currency come from there. One choice is shared by every
 * screen and kept in this browser. */
import { useSyncExternalStore } from 'react';
import { Select, useGet, useSession } from '@tenmina/web-ui';

export type WorkCountry = { code: string; name: string; currency: string; status?: string };
type PublicCountry = WorkCountry & { phone_prefix?: string; digital_address?: { name: string; example: string } | null; national_id_name?: string; land_registry_name?: string };

const KEY = 'tenmina.backoffice.country';
const listeners = new Set<() => void>();
let picked: string | null = null;

function read(): string | null {
  if (picked !== null) return picked;
  try { picked = window.localStorage.getItem(KEY) || ''; } catch { picked = ''; }
  return picked;
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

function choose(code: string) {
  picked = code;
  try { window.localStorage.setItem(KEY, code); } catch { /* private window: the choice lasts for this page only */ }
  listeners.forEach((fn) => fn());
}

/** The person's countries from the session (web-ui's Me type predates `work_countries`). */
export function useWorkCountries(): WorkCountry[] {
  const { me } = useSession();
  return ((me as unknown as { work_countries?: WorkCountry[] } | null)?.work_countries) ?? [];
}

/** The country this screen works in, its currency and name, and the other countries the person may switch to. */
export function useWorkCountry(): WorkCountry & { ready: boolean; choices: WorkCountry[]; setCode: (code: string) => void } {
  const choices = useWorkCountries();
  const stored = useSyncExternalStore(subscribe, read, () => '');
  const c = choices.find((x) => x.code === stored) ?? choices[0];
  return { code: c?.code ?? '', name: c?.name ?? '', currency: c?.currency ?? '', status: c?.status, ready: !!c, choices, setCode: choose };
}

/** A country's configuration (currency, wording) by code: from the session when it is one of the person's
 * countries, else from GET /v1/countries. Empty strings until it is known. */
export function useCountryInfo(code?: string | null): PublicCountry {
  const mine = useWorkCountries().find((x) => x.code === code);
  const all = useGet<PublicCountry[]>(code ? '/v1/countries' : null);
  const pub = (all.data ?? []).find((x) => x.code === code);
  const c = mine ?? pub;
  return { ...pub, code: code ?? '', name: c?.name ?? code ?? '', currency: c?.currency ?? '' };
}

/** "Country: Ghana", a switch when the person works in more than one country. */
export function CountryPick({ label = 'Country' }: { label?: string }) {
  const c = useWorkCountry();
  if (c.choices.length < 2) return null;
  return (
    <label className="row" style={{ gap: 8, alignItems: 'center' }}>
      <span className="muted">{label}</span>
      <Select value={c.code} onChange={(e) => c.setCode(e.target.value)} aria-label={label} style={{ width: 'auto' }}>
        {c.choices.map((x) => <option key={x.code} value={x.code}>{x.name}{x.status && x.status !== 'active' ? ` (${x.status.replace(/_/g, ' ')})` : ''}</option>)}
      </Select>
    </label>
  );
}
