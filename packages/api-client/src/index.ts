/**
 * One typed client for the Tenmina API, shared by the portal, the back office
 * and both apps (document 02, 7.1, ADR-22). Types are generated from the
 * API's OpenAPI schema: run `pnpm --filter @tenmina/api-client generate`.
 *
 * Web apps use the session cookie and X-CSRFToken (mode "cookie"); the apps
 * use bearer tokens (mode "bearer").
 */
import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';

export type { paths, components } from './schema';

export type Problem = {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  blocking_reasons?: { rule: string; message: string }[];
  errors?: { pointer: string; message: string }[];
  trace_id?: string;
};

export class ApiError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail || problem.title);
  }
}

export type ClientOptions = {
  baseUrl?: string;
  mode: 'cookie' | 'bearer';
  getToken?: () => string | null | undefined;
  app?: string; // Tenmina-App header, e.g. "field/ios/1.4.0"
  onUnauthenticated?: () => void;
};

function readCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith(name + '='))
    ?.split('=')[1];
}

function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function createTenminaClient(opts: ClientOptions) {
  const client = createClient<paths>({
    baseUrl: opts.baseUrl ?? '',
    credentials: opts.mode === 'cookie' ? 'include' : 'omit',
  });
  const mw: Middleware = {
    onRequest({ request }) {
      if (opts.mode === 'bearer') {
        const t = opts.getToken?.();
        if (t) request.headers.set('Authorization', `Bearer ${t}`);
      } else if (request.method !== 'GET') {
        const csrf = readCookie('csrftoken');
        if (csrf) request.headers.set('X-CSRFToken', csrf);
      }
      if (request.method === 'POST' && !request.headers.has('Idempotency-Key')) {
        request.headers.set('Idempotency-Key', uuid());
      }
      if (opts.app) request.headers.set('Tenmina-App', opts.app);
      return request;
    },
    async onResponse({ response }) {
      if (response.status === 401) opts.onUnauthenticated?.();
      return response;
    },
  };
  client.use(mw);
  return client;
}

export type TenminaClient = ReturnType<typeof createTenminaClient>;

/** Unwrap an openapi-fetch result: return data or throw ApiError. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || !response.ok) {
    const prob = (error ?? {}) as Partial<Problem>;
    throw new ApiError({
      type: prob.type ?? 'about:blank',
      title: prob.title ?? response.statusText,
      status: prob.status ?? response.status,
      detail: prob.detail ?? response.statusText,
      code: prob.code ?? 'error',
      blocking_reasons: prob.blocking_reasons,
      errors: prob.errors,
      trace_id: prob.trace_id,
    });
  }
  return data as T;
}

export type Money = { amount: string; currency: string };

export function formatMoney(m: Money | null | undefined, locale = 'en-GB'): string {
  if (!m) return '—';
  const n = Number(m.amount);
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency: m.currency }).format(n);
  } catch {
    return `${m.currency} ${n.toFixed(2)}`;
  }
}
