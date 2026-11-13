'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, CodeBoxes, Field, Input, Mark, ProblemBox, useSession } from '@tenmina/web-ui';
import { ApiError } from '@tenmina/api-client';
import { ROLE_HOME } from '@/lib/nav';

function LoginForm() {
  const { signIn } = useSession();
  const router = useRouter();
  const next = useSearchParams().get('next');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await signIn(email, password, needCode ? code : undefined);
      const roleHome = me.roles.map((r) => ROLE_HOME[r]).find(Boolean);
      router.replace(next || (me.roles.includes('CL') ? '/' : roleHome || '/'));
    } catch (err) {
      if (err instanceof ApiError && err.problem.code === 'mfa-required') setNeedCode(true);
      else setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="stack" style={{ width: 'min(420px, 100%)' }}>
      <div className="row"><Mark size={36} /><strong style={{ fontSize: 20 }}>Tenmina</strong></div>
      <h1>Sign in</h1>
      <Field label="Email"><Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
      <Field label="Password"><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
      {needCode ? <Field label="Code from your authenticator app"><CodeBoxes value={code} onChange={setCode} autoFocus /></Field> : null}
      <ProblemBox error={error} />
      <Button variant="primary" busy={busy} type="submit" block>{needCode ? 'Confirm' : 'Sign in'}</Button>
      <p className="muted">New to Tenmina? <Link href="/register">Create an account</Link></p>
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
