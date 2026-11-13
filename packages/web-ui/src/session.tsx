'use client';
/* Session for the two web apps: cookie sign-in with CSRF (02, 7.1). */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { createTenminaClient, type TenminaClient } from '@tenmina/api-client';
import { ApiProvider, call } from './data';

export type Me = {
  id: string; email: string; full_name: string; phone: string; roles: string[];
  mfa_enabled: boolean; preferred_language: string; residence_country: string; home_country: string | null;
};

type SessionCtx = {
  me: Me | null;
  loading: boolean;
  client: TenminaClient;
  signIn: (email: string, password: string, code?: string) => Promise<Me>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  stepUp: (code: string) => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
};

const Ctx = createContext<SessionCtx | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const client = useMemo(() => createTenminaClient({ mode: 'cookie' }), []);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await call<Me>(client, 'GET', '/v1/me'));
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    call(client, 'GET', '/v1/auth/csrf').catch(() => undefined).finally(refresh);
  }, [client, refresh]);

  const value: SessionCtx = {
    me, loading, client, refresh,
    signIn: async (email, password, code) => {
      await call(client, 'GET', '/v1/auth/csrf');
      const p = await call<Me>(client, 'POST', '/v1/auth/login', { email, password, code });
      setMe(p);
      await call(client, 'GET', '/v1/auth/csrf');
      return p;
    },
    signOut: async () => {
      await call(client, 'POST', '/v1/auth/logout').catch(() => undefined);
      setMe(null);
    },
    stepUp: async (code) => {
      await call(client, 'POST', '/v1/auth/mfa/step-up', { code });
    },
    hasRole: (...roles) => !!me && roles.some((r) => me.roles.includes(r)),
  };
  return (
    <Ctx.Provider value={value}>
      <ApiProvider client={client}>{children}</ApiProvider>
    </Ctx.Provider>
  );
}

export function useSession(): SessionCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('SessionProvider missing');
  return c;
}
