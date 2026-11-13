'use client';
/* Data hooks over the typed client, with SWR caching. */
import React, { createContext, useContext } from 'react';
import useSWR, { type SWRConfiguration } from 'swr';
import { ApiError, type TenminaClient } from '@tenmina/api-client';

const Ctx = createContext<TenminaClient | null>(null);

export function ApiProvider({ client, children }: { client: TenminaClient; children: React.ReactNode }) {
  return <Ctx.Provider value={client}>{children}</Ctx.Provider>;
}

export function useClient(): TenminaClient {
  const c = useContext(Ctx);
  if (!c) throw new Error('ApiProvider missing');
  return c;
}

/** Plain JSON fetch through the same client middleware (CSRF, Idempotency-Key). */
export async function call<T = unknown>(client: TenminaClient, method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body?: unknown, query?: Record<string, unknown>): Promise<T> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fn = (client as any)[method] as (p: string, o: unknown) => Promise<{ data?: T; error?: unknown; response: Response }>;
  const { data, error, response } = await fn(path, { body, params: { query } });
  if (error !== undefined || !response.ok) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const e = (error ?? {}) as any;
    throw new ApiError({ type: e.type ?? '', title: e.title ?? response.statusText, status: response.status, detail: e.detail ?? '', code: e.code ?? 'error', blocking_reasons: e.blocking_reasons, errors: e.errors });
  }
  return data as T;
}

/** useGet('/v1/cases', {status: 'open'}) → {data, error, isLoading, mutate}. Pass null path to skip. */
export function useGet<T = unknown>(path: string | null, query?: Record<string, unknown>, cfg?: SWRConfiguration) {
  const client = useClient();
  return useSWR<T>(path ? [path, JSON.stringify(query ?? {})] : null, () => call<T>(client, 'GET', path as string, undefined, query), cfg);
}

export type Page<T> = { items: T[]; next_cursor: string | null };
