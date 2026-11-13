import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError, APP_VERSION, MobileApi, OfflineError, platformName, toProblem, type AppName, type Problem, type UpdateRequired } from './api';
import { secureDelete, secureGet, secureSet } from './storage';

/** The signed-in person, as GET /v1/me returns it. */
export interface Person {
  id: string;
  email: string;
  phone: string;
  full_name: string;
  preferred_language: string;
  residence_country: string;
  home_country: string;
  mfa_enabled: boolean;
  roles: string[];
  status: string;
  id_check_status: string;
  email_verified: boolean;
  phone_verified: boolean;
  preferred_channel: string;
  channels_off: string[];
  privacy_notice_pending: unknown;
  created_at: string;
}

/** GET /v1/mobile/app-config: minimum version, store link and how fees are paid (FR-APP-005, FR-APP-006). */
export interface AppConfig {
  app: string;
  platform: string;
  min_version: string;
  latest_version: string;
  min_raised_at: string | null;
  store_url: string;
  update_required: boolean;
  update_available: boolean;
  /** "web": fees open the portal checkout in the browser; never an in-app purchase (DA-12). */
  fee_payment_mode: string;
}

export type SignInResult = { ok: true } | { ok: false; needsCode: true; problem?: Problem } | { ok: false; needsCode?: false; problem: Problem };

interface Session {
  api: MobileApi;
  app: AppName;
  status: 'loading' | 'signedOut' | 'signedIn';
  me: Person | null;
  /** True when the app is working from what it saved last time, without a connection. */
  offline: boolean;
  config: AppConfig | null;
  update: UpdateRequired | null;
  signIn: (identifier: string, password: string, code?: string) => Promise<SignInResult>;
  signOut: () => Promise<void>;
  /** Take a token pair from another sign-in route (sign-up codes). */
  adopt: (out: { person: Person; access: string; refresh: string; expires_in: number }) => Promise<void>;
  reloadMe: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
}

const SessionContext = createContext<Session | null>(null);
const ME_KEY = 'tenmina.me';

/**
 * Real sign-in for both apps (FR-ACC-001 to FR-ACC-003): email or phone and a
 * password, then the authenticator code when the account has MFA. Tokens stay
 * in secure storage, so the app opens signed in next time.
 */
export function SessionProvider({ app, children }: { app: AppName; children: ReactNode }) {
  const api = useMemo(() => new MobileApi(app), [app]);
  const [status, setStatus] = useState<Session['status']>('loading');
  const [me, setMe] = useState<Person | null>(null);
  const [offline, setOffline] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [update, setUpdate] = useState<UpdateRequired | null>(null);
  const started = useRef(false);

  const keepMe = useCallback(async (p: Person | null) => {
    setMe(p);
    if (p) await secureSet(ME_KEY, JSON.stringify(p));
    else await secureDelete(ME_KEY);
  }, []);

  useEffect(
    () =>
      api.on((e) => {
        if (e.kind === 'update') setUpdate(e.info);
        if (e.kind === 'signedOut') {
          void keepMe(null);
          setStatus('signedOut');
        }
      }),
    [api, keepMe],
  );

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        const c = await api.request<AppConfig>('GET', '/v1/mobile/app-config', {
          anonymous: true,
          query: { app, platform: platformName(), version: APP_VERSION },
        });
        setConfig(c);
        if (c.update_required) setUpdate({ minVersion: c.min_version, storeUrl: c.store_url, detail: 'Please update Tenmina from the store.' });
      } catch {
        // Offline at start: the version is checked again on every call.
      }
      const t = await api.loadTokens();
      if (!t) {
        setStatus('signedOut');
        return;
      }
      try {
        await keepMe(await api.get<Person>('/v1/me'));
        setStatus('signedIn');
      } catch (e) {
        if (e instanceof OfflineError) {
          // No signal: carry on with what this phone saved, so field work goes on offline (FR-MOB-005).
          const raw = await secureGet(ME_KEY);
          if (raw) {
            setMe(JSON.parse(raw) as Person);
            setOffline(true);
            setStatus('signedIn');
            return;
          }
        }
        if (e instanceof ApiError && e.problem.status === 401) await api.setTokens(null);
        setStatus(api.hasTokens() ? 'signedIn' : 'signedOut');
      }
    })();
  }, [api, app, keepMe]);

  const signIn = useCallback(
    async (identifier: string, password: string, code?: string): Promise<SignInResult> => {
      try {
        await api.setTokens(null);
        const out = await api.request<{ person: Person; access: string; refresh: string; expires_in: number }>('POST', '/v1/auth/token', {
          anonymous: true,
          body: { identifier: identifier.trim(), password, ...(code ? { code } : {}) },
        });
        await api.setTokens(out);
        await keepMe(out.person);
        setOffline(false);
        setStatus('signedIn');
        return { ok: true };
      } catch (e) {
        const problem = toProblem(e);
        if (problem.code === 'mfa-required') return { ok: false, needsCode: true };
        if (problem.code === 'mfa-invalid') return { ok: false, needsCode: true, problem };
        return { ok: false, problem };
      }
    },
    [api, keepMe],
  );

  const signOut = useCallback(async () => {
    await api.signOut();
    await keepMe(null);
    setStatus('signedOut');
  }, [api, keepMe]);

  const adopt = useCallback(
    async (out: { person: Person; access: string; refresh: string; expires_in: number }) => {
      await api.setTokens(out);
      await keepMe(out.person);
      setOffline(false);
      setStatus('signedIn');
    },
    [api, keepMe],
  );

  const reloadMe = useCallback(async () => {
    try {
      await keepMe(await api.get<Person>('/v1/me'));
      setOffline(false);
    } catch {
      // keep what we have
    }
  }, [api, keepMe]);

  const value = useMemo<Session>(
    () => ({
      api,
      app,
      status,
      me,
      offline,
      config,
      update,
      signIn,
      signOut,
      adopt,
      reloadMe,
      hasRole: (...roles: string[]) => !!me && me.roles.some((r) => roles.includes(r)),
    }),
    [api, app, status, me, offline, config, update, signIn, signOut, adopt, reloadMe],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error('useSession must be used inside SessionProvider');
  return s;
}

export function useApi(): MobileApi {
  return useSession().api;
}
