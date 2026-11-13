'use client';
/* Partner console. The partner API (FR-PTR-001 to FR-PTR-004) accepts only the partner's own client
   credentials; this page asks for them, keeps the short-lived token in this browser tab only, and calls
   the same metered endpoints a partner's systems use. Tenmina never sees the secret again. */
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { ApiError } from '@tenmina/api-client';
import { Button, Card, Field, Input, ProblemBox } from '@tenmina/web-ui';

type Tok = { token: string; expires: number; scope: string; client: string };
const KEY = 'tenmina.partner.token';
const Ctx = createContext<{ tok: Tok | null; call: <T>(method: string, path: string, body?: unknown) => Promise<T>; signOut: () => void } | null>(null);

function load(): Tok | null {
  try {
    const t = JSON.parse(sessionStorage.getItem(KEY) || 'null') as Tok | null;
    return t && t.expires > Date.now() + 5000 ? t : null;
  } catch { return null; }
}

export function PartnerGate({ children }: { children: React.ReactNode }) {
  const [tok, setTok] = useState<Tok | null>(null);
  const [ready, setReady] = useState(false);
  const [id, setId] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { setTok(load()); setReady(true); }, []);

  const signOut = useCallback(() => { try { sessionStorage.removeItem(KEY); } catch { /* ignore */ } setTok(null); }, []);
  const call = useCallback(async <T,>(method: string, path: string, body?: unknown): Promise<T> => {
    const t = load();
    if (!t) { setTok(null); throw new ApiError({ type: '', title: 'Your partner session ended', status: 401, detail: 'Enter your client credentials again.', code: 'unauthenticated' }); }
    const res = await fetch(path, { method, headers: { Authorization: `Bearer ${t.token}`, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'omit' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const data: any = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError({ type: data.type ?? '', title: data.title ?? res.statusText, status: res.status, detail: data.detail ?? '', code: data.code ?? 'error', errors: data.errors, blocking_reasons: data.blocking_reasons });
    return data as T;
  }, []);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const res = await fetch('/v1/partner/oauth/token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'omit', body: JSON.stringify({ grant_type: 'client_credentials', client_id: id, client_secret: secret }) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const d: any = await res.json().catch(() => ({}));
      if (!res.ok) throw new ApiError({ type: '', title: d.title ?? 'Those credentials did not work', status: res.status, detail: d.detail ?? '', code: d.code ?? 'error' });
      const t: Tok = { token: d.access_token, expires: Date.now() + d.expires_in * 1000, scope: d.scope, client: id };
      try { sessionStorage.setItem(KEY, JSON.stringify(t)); } catch { /* the token then lives only in memory */ }
      setTok(t); setSecret('');
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  if (!ready) return null;
  if (!tok) {
    return (
      <form className="stack" onSubmit={connect} style={{ maxWidth: 520 }}>
        <h1>Connect your API client</h1>
        <p className="muted">Enter the client ID and secret Tenmina issued to your organisation. The token lasts 15 minutes and stays in this browser tab. Every call is metered like your system&apos;s calls.</p>
        <Card className="stack">
          <Field label="Client ID"><Input value={id} onChange={(e) => setId(e.target.value)} autoComplete="username" required /></Field>
          <Field label="Client secret"><Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="current-password" required /></Field>
          <ProblemBox error={error} />
          <Button variant="primary" type="submit" busy={busy}>Connect</Button>
        </Card>
      </form>
    );
  }
  return <Ctx.Provider value={{ tok, call, signOut }}>{children}</Ctx.Provider>;
}

export function usePartner() {
  const c = useContext(Ctx);
  if (!c) throw new Error('PartnerGate missing');
  return c;
}

export function PartnerBar() {
  const { tok, signOut } = usePartner();
  return (
    <div className="spread" style={{ fontSize: 14 }}>
      <span className="muted">Connected as <span className="mono">{tok?.client}</span> until {tok ? new Date(tok.expires).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''}</span>
      <Button size="sm" variant="ghost" onClick={signOut}>Disconnect</Button>
    </div>
  );
}
