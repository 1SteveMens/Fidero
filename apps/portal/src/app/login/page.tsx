'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, CodeBoxes, Field, Input, Mark, ProblemBox, call, useClient, useSession } from '@tenmina/web-ui';
import { ApiError } from '@tenmina/api-client';
import { ROLE_HOME } from '@/lib/nav';
import { callFull } from '@/components/secondfactor';

/** Where the second factor comes from (FR-ACC-003, FR-ACC-015): the authenticator app, or a code sent by SMS. */
type Ask = { method: 'totp' | 'sms'; sentTo?: string };

/**
 * Sign in (SCR-PTL-03): email and password, then the second factor. A client
 * without an authenticator gets a 6-digit code by SMS to the confirmed number:
 * "We sent a code to +44 •••• 123", the six boxes and "Send a new code".
 * Staff and anyone who set one up use the authenticator app.
 */
function LoginForm() {
  const { refresh } = useSession();
  const client = useClient();
  const router = useRouter();
  const next = useSearchParams().get('next');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [ask, setAsk] = useState<Ask | null>(null);
  const [resent, setResent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function attempt(withCode: boolean) {
    setBusy(true);
    setError(null);
    try {
      // Like the session's signIn, but keeps the problem's `method` and `sent_to` (FR-ACC-015).
      await call(client, 'GET', '/v1/auth/csrf');
      const me = await callFull<{ roles: string[] }>(client, 'POST', '/v1/auth/login', { email, password, ...(withCode ? { code } : {}) });
      await call(client, 'GET', '/v1/auth/csrf');
      await refresh();
      const roleHome = me.roles.map((r) => ROLE_HOME[r]).find(Boolean);
      router.replace(next || (me.roles.includes('CL') ? '/' : roleHome || '/'));
    } catch (err) {
      if (err instanceof ApiError && err.problem.code === 'mfa-required') {
        const p = err.problem as ApiError['problem'] & { method?: string; sent_to?: string };
        setAsk(p.method === 'sms' ? { method: 'sms', sentTo: p.sent_to } : { method: 'totp' });
        setCode('');
        setResent(!withCode && !!ask);
      } else {
        setError(err);
        if (withCode) setCode('');
      }
    } finally {
      setBusy(false);
    }
  }

  const sms = ask?.method === 'sms';
  return (
    <form onSubmit={(e) => { e.preventDefault(); void attempt(!!ask); }} className="stack" style={{ width: 'min(420px, 100%)' }}>
      <div className="row"><Mark size={36} /><strong style={{ fontSize: 20 }}>Tenmina</strong></div>
      <h1>{ask ? 'Enter your code' : 'Sign in'}</h1>
      {!ask ? (
        <>
          <Field label="Email"><Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
          <Field label="Password"><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
        </>
      ) : sms ? (
        <div className="stack" style={{ gap: 10 }}>
          <p style={{ margin: 0 }}>We sent a code to <strong className="mono">{ask.sentTo ?? 'your phone'}</strong>. It works for 5 minutes.</p>
          <Field label="Code from the text message"><CodeBoxes value={code} onChange={setCode} autoFocus /></Field>
          <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} disabled={busy} onClick={() => void attempt(false)}>
            {resent ? 'Sent again. Send another' : 'Send a new code'}
          </button>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Do not share this code. Tenmina will never call you for it.</p>
        </div>
      ) : (
        <Field label="Code from your authenticator app"><CodeBoxes value={code} onChange={setCode} autoFocus /></Field>
      )}
      <ProblemBox error={error} />
      <Button variant="primary" busy={busy} type="submit" disabled={!!ask && code.length !== 6} block>{ask ? 'Confirm and sign in' : 'Sign in'}</Button>
      {ask ? (
        <button type="button" className="btn btn-ghost" onClick={() => { setAsk(null); setCode(''); setError(null); }}>Use a different account</button>
      ) : (
        <p className="muted">New to Tenmina? <Link href="/register">Create an account</Link></p>
      )}
    </form>
  );
}

export default function Login() {
  return (
    <main className="ground-ink" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <Suspense><LoginForm /></Suspense>
    </main>
  );
}
