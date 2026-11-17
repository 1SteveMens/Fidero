'use client';
import Link from 'next/link';
import { useCallback, useState } from 'react';
import { Button, CodeBoxes, ProblemBox, useClient, useSession } from '@tenmina/web-ui';
import { ApiError, type TenminaClient } from '@tenmina/api-client';

/**
 * Like web-ui's call(), but the thrown problem keeps every field the API sent
 * (RFC 9457 extension members such as `method`, `sent_to`, `paused_until`).
 */
export async function callFull<T = unknown>(client: TenminaClient, method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fn = (client as any)[method] as (p: string, o: unknown) => Promise<{ data?: T; error?: unknown; response: Response }>;
  const { data, error, response } = await fn(path, { body });
  if (error !== undefined || !response.ok) {
    const e = (error ?? {}) as Record<string, unknown> & { title?: string; detail?: string; code?: string; type?: string };
    throw new ApiError({ ...e, type: e.type ?? '', title: e.title ?? response.statusText, status: response.status, detail: e.detail ?? '', code: e.code ?? 'error' } as ApiError['problem']);
  }
  return data as T;
}

/** What GET /v1/me adds for the second factor (FR-ACC-003, FR-ACC-015). */
export type SmsPause = { reason: 'phone_changed' | 'sim_swap'; until: string; detail: string };
type MeFactor = { mfa_enabled: boolean; second_factor?: 'authenticator' | 'sms' | 'none'; phone_masked?: string; sms_pause?: SmsPause | null };

export type WebMethod = 'totp' | 'sms' | 'paused' | 'none';

export interface WebFactor {
  /** "totp": the authenticator code. "sms": a code sent by SMS. "paused": SMS approvals are paused. "none": nothing set up. */
  method: WebMethod;
  phone: string;
  pause: SmsPause | null;
  code: string;
  setCode: (v: string) => void;
  /** SMS: where the last code went, once sent. */
  sentTo: string | null;
  sending: boolean;
  sendError: unknown;
  send: () => Promise<void>;
  /** Six digits are in. */
  ready: boolean;
  /** POST /v1/auth/mfa/step-up with the code; valid for 5 minutes. Throws the API's problem. */
  stepUp: () => Promise<void>;
  reset: () => void;
}

/** The person's own second-factor fields from the session (web-ui's Me type predates them). */
export function useMeFactor(): MeFactor | null {
  const { me } = useSession();
  return me as unknown as MeFactor | null;
}

/**
 * The second factor for one approval on the web (FR-ACC-003, FR-ACC-015):
 * the authenticator code for anyone who set one up (always for staff), else a
 * 6-digit code sent by SMS to the client's confirmed number. SMS approvals
 * pause for 72 hours after a number change or a reported SIM swap.
 */
export function useWebFactor(): WebFactor {
  const me = useMeFactor();
  const { refresh } = useSession();
  const client = useClient();
  const [code, setCode] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);
  const [pausedNow, setPausedNow] = useState<SmsPause | null>(null);
  const pause = pausedNow ?? me?.sms_pause ?? null;
  const method: WebMethod = !me ? 'none' : me.mfa_enabled ? 'totp' : me.second_factor === 'sms' ? (pause ? 'paused' : 'sms') : 'none';

  const send = useCallback(async () => {
    setSending(true);
    setSendError(null);
    try {
      const r = await callFull<{ sent_to: string }>(client, 'POST', '/v1/auth/mfa/sms');
      setSentTo(r.sent_to);
      setCode('');
    } catch (e) {
      const p = e instanceof ApiError ? (e.problem as ApiError['problem'] & { reason?: SmsPause['reason']; paused_until?: string }) : null;
      if (p?.code === 'sms-paused') {
        setPausedNow({ reason: p.reason ?? 'phone_changed', until: p.paused_until ?? '', detail: p.detail });
        void refresh();
      } else setSendError(e);
    } finally {
      setSending(false);
    }
  }, [client, refresh]);

  const stepUp = useCallback(async () => {
    try {
      await callFull(client, 'POST', '/v1/auth/mfa/step-up', method === 'sms' ? { method: 'sms', code } : { code });
    } catch (e) {
      setCode('');
      if (e instanceof ApiError && e.problem.code === 'sms-paused') void refresh();
      throw e;
    }
  }, [client, code, method, refresh]);

  return {
    method,
    phone: me?.phone_masked ?? '',
    pause,
    code,
    setCode,
    sentTo,
    sending,
    sendError,
    send,
    ready: (method === 'totp' || (method === 'sms' && !!sentTo)) && code.length === 6,
    stepUp,
    reset: () => setCode(''),
  };
}

/**
 * The code part of an approval: the authenticator's six boxes; or "Send code",
 * then "We sent a code to +44 •••• 123", the six boxes and "Send a new code";
 * or why SMS approvals are paused; or where to confirm a number.
 */
export function FactorField({ f, autoFocus }: { f: WebFactor; autoFocus?: boolean }) {
  if (f.method === 'none') {
    return (
      <div className="card stack" style={{ border: '2px solid var(--orange)' }}>
        <strong>Confirm your mobile number first.</strong>
        <span className="muted">Every approval needs a code we text you, or the code from an authenticator app.</span>
        <Link className="btn btn-primary" href="/account/profile">Confirm your number</Link>
      </div>
    );
  }
  if (f.method === 'paused') return <SmsPausedCard pause={f.pause} />;
  if (f.method === 'totp') {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <span className="muted">Code from your authenticator app</span>
        <CodeBoxes value={f.code} onChange={f.setCode} autoFocus={autoFocus} />
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      {f.sentTo ? (
        <>
          <span>We sent a code to <strong className="mono">{f.sentTo}</strong>. It works for 5 minutes.</span>
          <CodeBoxes value={f.code} onChange={f.setCode} autoFocus />
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void f.send()} disabled={f.sending} aria-busy={f.sending || undefined} style={{ alignSelf: 'flex-start' }}>
            Send a new code
          </button>
          <span className="muted" style={{ fontSize: 13 }}>Do not share this code. Tenmina will never call you for it.</span>
        </>
      ) : (
        <>
          <span>We text a 6-digit code to <strong className="mono">{f.phone || 'your phone'}</strong>.</span>
          <Button variant="dark" busy={f.sending} onClick={() => void f.send()} block>Send code</Button>
        </>
      )}
      <ProblemBox error={f.sendError} />
    </div>
  );
}

/** Why approvals by text message are paused, and until when. Orange: it needs this person. */
export function SmsPausedCard({ pause }: { pause: SmsPause | null }) {
  return (
    <div className="card stack" role="status" style={{ border: '2px solid var(--orange)', gap: 6 }}>
      <div className="label" style={{ color: 'var(--orange)' }}>Approvals by text message are paused</div>
      <span>{pause?.detail ?? 'Approvals by text message pause for 72 hours after your number changes.'}</span>
    </div>
  );
}
