import { Platform } from 'react-native';
import Constants from 'expo-constants';
import { ApiError, createTenminaClient, type Problem } from '@tenmina/api-client';
import { secureDelete, secureGet, secureSet } from './storage';

export { ApiError, type Problem };

/** Which of the two apps is calling: the Tenmina-App header names it (02 section 8.10). */
export type AppName = 'client' | 'field';
export type PlatformName = 'ios' | 'android';

/** The store build's version, from app.json. */
export const APP_VERSION: string = Constants.expoConfig?.version ?? '1.0.0';

/**
 * The platform the API sees. The web preview is a development tool only and
 * calls itself iOS, the phone the founder tests on.
 */
export function platformName(): PlatformName {
  return Platform.OS === 'android' ? 'android' : 'ios';
}

/** The API's address, from EXPO_PUBLIC_API_URL at build time (a phone cannot reach "localhost"). */
export function apiBaseUrl(): string {
  return (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
}

/** The portal's address, for the few things the apps open on the web (fees in web mode, listings). */
export function portalUrl(): string {
  return (process.env.EXPO_PUBLIC_PORTAL_URL ?? 'http://localhost:3000').replace(/\/$/, '');
}

export interface Tokens {
  access: string;
  refresh: string;
  /** Epoch milliseconds when the access token stops working. */
  expiresAt: number;
}

export interface UpdateRequired {
  minVersion: string;
  storeUrl: string;
  detail: string;
}

export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  /** Raw bytes (an evidence upload): sent as is with this content type. */
  raw?: { data: Blob | ArrayBuffer | Uint8Array; contentType: string };
  /** A multipart form (a document or photo upload); the boundary is set by fetch. */
  form?: FormData;
  headers?: Record<string, string>;
  /** A stable key so a retried offline submission never doubles (7.1). */
  idempotencyKey?: string;
  /** Skip the token, for sign-in and the public app config. */
  anonymous?: boolean;
}

const TOKEN_KEY = 'tenmina.tokens';
/** Refresh this long before the access token runs out. */
const EARLY_MS = 60_000;

/** A network failure, not a problem from the API: the phone is offline or the server is unreachable. */
export class OfflineError extends Error {
  constructor() {
    super('No connection to Tenmina. Check your signal and try again.');
  }
}

function problemFrom(status: number, statusText: string, body: unknown): Problem & Record<string, unknown> {
  const p = (body && typeof body === 'object' ? body : {}) as Partial<Problem> & Record<string, unknown>;
  return {
    ...p,
    type: p.type ?? 'about:blank',
    title: p.title ?? statusText ?? 'Error',
    status: p.status ?? status,
    detail: p.detail ?? (typeof body === 'string' && body ? body : statusText || 'Something went wrong.'),
    code: p.code ?? (status === 0 ? 'offline' : 'error'),
    blocking_reasons: p.blocking_reasons,
    errors: p.errors,
    trace_id: p.trace_id,
  };
}

/**
 * The apps' connection to /v1, built on the shared typed client in bearer mode
 * (02 section 7.1, ADR-22). Tokens are kept in secure storage, refreshed before
 * they run out and once more on a 401. A 426 app-version-unsupported tells the
 * app to show "Update required" (FR-APP-006).
 */
export class MobileApi {
  readonly app: AppName;
  readonly header: string;
  private tokens: Tokens | null = null;
  private refreshing: Promise<boolean> | null = null;
  private client;
  /** Same client without the token, for sign-in and refresh: an expired token must not ride along. */
  private anonClient;
  private listeners = new Set<(e: { kind: 'signedOut' } | { kind: 'update'; info: UpdateRequired }) => void>();

  constructor(app: AppName) {
    this.app = app;
    this.header = `${app}/${platformName()}/${APP_VERSION}`;
    this.client = createTenminaClient({
      mode: 'bearer',
      baseUrl: apiBaseUrl(),
      app: this.header,
      getToken: () => this.tokens?.access,
    });
    this.anonClient = createTenminaClient({ mode: 'bearer', baseUrl: apiBaseUrl(), app: this.header });
  }

  on(fn: (e: { kind: 'signedOut' } | { kind: 'update'; info: UpdateRequired }) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(e: { kind: 'signedOut' } | { kind: 'update'; info: UpdateRequired }) {
    this.listeners.forEach((fn) => fn(e));
  }

  async loadTokens(): Promise<Tokens | null> {
    const raw = await secureGet(TOKEN_KEY);
    try {
      this.tokens = raw ? (JSON.parse(raw) as Tokens) : null;
    } catch {
      this.tokens = null;
    }
    return this.tokens;
  }

  hasTokens(): boolean {
    return !!this.tokens;
  }

  async setTokens(t: { access: string; refresh: string; expires_in: number } | null): Promise<void> {
    if (!t) {
      this.tokens = null;
      await secureDelete(TOKEN_KEY);
      return;
    }
    this.tokens = { access: t.access, refresh: t.refresh, expiresAt: Date.now() + t.expires_in * 1000 };
    await secureSet(TOKEN_KEY, JSON.stringify(this.tokens));
  }

  /** Swap the refresh token for a new pair. A reused or expired refresh token means signing in again. */
  private async refresh(): Promise<boolean> {
    if (!this.tokens) return false;
    if (this.refreshing) return this.refreshing;
    const refresh = this.tokens.refresh;
    this.refreshing = (async () => {
      try {
        const out = await this.send<{ access: string; refresh: string; expires_in: number }>('POST', '/v1/auth/refresh', { body: { refresh }, anonymous: true });
        await this.setTokens(out);
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.problem.status === 401) {
          await this.setTokens(null);
          this.emit({ kind: 'signedOut' });
        }
        return false;
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  /** One HTTP call through openapi-fetch. Throws ApiError for a problem, OfflineError when there is no connection. */
  private async send<T>(method: Method, path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json, application/problem+json', ...(opts.headers ?? {}) };
    if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;
    const query = opts.query ? Object.fromEntries(Object.entries(opts.query).filter(([, v]) => v !== undefined && v !== null && v !== '')) : undefined;
    const init: Record<string, unknown> = { params: { query }, headers };
    if (opts.form) {
      init.body = opts.form;
      init.bodySerializer = (b: unknown) => b;
    } else if (opts.raw) {
      headers['Content-Type'] = opts.raw.contentType;
      init.body = opts.raw.data;
      init.bodySerializer = (b: unknown) => b;
    } else if (opts.body !== undefined) {
      init.body = opts.body;
    }
    let res: { data?: unknown; error?: unknown; response: Response };
    try {
      // Paths are built at run time (ids in them), so the typed path union is not used here.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      res = await ((opts.anonymous ? this.anonClient : this.client) as any).request(method.toLowerCase(), path, init);
    } catch {
      throw new OfflineError();
    }
    const { data, error, response } = res;
    if (error !== undefined || !response.ok) {
      const problem = problemFrom(response.status, response.statusText, error);
      if (problem.code === 'app-version-unsupported' || response.status === 426) {
        this.emit({
          kind: 'update',
          info: { minVersion: String(problem.min_version ?? ''), storeUrl: String(problem.store_url ?? ''), detail: problem.detail },
        });
      }
      throw new ApiError(problem);
    }
    return data as T;
  }

  /** A call with the signed-in person's token: refreshed first when it is about to run out, and retried once on a 401. */
  async request<T>(method: Method, path: string, opts: RequestOptions = {}): Promise<T> {
    if (opts.anonymous) return this.send<T>(method, path, opts);
    if (this.tokens && this.tokens.expiresAt - Date.now() < EARLY_MS) await this.refresh();
    try {
      return await this.send<T>(method, path, opts);
    } catch (e) {
      if (e instanceof ApiError && e.problem.status === 401 && e.problem.code !== 'mfa-required' && this.tokens) {
        if (await this.refresh()) return this.send<T>(method, path, opts);
      }
      throw e;
    }
  }

  get<T>(path: string, query?: RequestOptions['query']): Promise<T> {
    return this.request<T>('GET', path, { query });
  }

  post<T>(path: string, body?: unknown, opts: Omit<RequestOptions, 'body'> = {}): Promise<T> {
    return this.request<T>('POST', path, { ...opts, body: body ?? {} });
  }

  put<T>(path: string, body?: unknown, opts: Omit<RequestOptions, 'body'> = {}): Promise<T> {
    return this.request<T>('PUT', path, { ...opts, body: body ?? {} });
  }

  del<T>(path: string): Promise<T> {
    return this.request<T>('DELETE', path);
  }

  /** Sign-out: revoke both tokens on the server, then forget them here. */
  async signOut(): Promise<void> {
    const refresh = this.tokens?.refresh;
    try {
      if (this.tokens) await this.send('POST', '/v1/auth/logout', { body: { refresh } });
    } catch {
      // Offline or already revoked: forgetting them here is what matters.
    }
    await this.setTokens(null);
  }
}

/** A problem in a form a screen can show, from anything a call may throw. */
export function toProblem(e: unknown): Problem {
  if (e instanceof ApiError) return e.problem;
  if (e instanceof OfflineError) return problemFrom(0, 'Offline', { detail: e.message, code: 'offline', title: 'No connection' });
  return problemFrom(0, 'Error', { detail: e instanceof Error ? e.message : 'Something went wrong.' });
}

/** A client-generated id for offline items and idempotency keys (RFC 4122 version 4). */
export function newUuid(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
