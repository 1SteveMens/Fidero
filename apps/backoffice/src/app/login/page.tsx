'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, CodeBoxes, Field, Input, Mark, ProblemBox, useSession } from '@tenmina/web-ui';
import { ApiError } from '@tenmina/api-client';

export default function Login() {
  const { signIn } = useSession();
  const router = useRouter();
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
      await signIn(email, password, needCode ? code : undefined);
      router.replace('/');
    } catch (err) {
      if (err instanceof ApiError && err.problem.code === 'mfa-required') setNeedCode(true);
      else setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="ground-ink" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form onSubmit={submit} className="stack" style={{ width: 'min(420px, 100%)' }}>
        <div className="row"><Mark size={36} /><strong style={{ fontSize: 20 }}>Back office</strong></div>
        <h1>Sign in</h1>
        <Field label="Email"><Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <Field label="Password"><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
        {needCode ? (
          <Field label="Code from your authenticator app"><CodeBoxes value={code} onChange={setCode} autoFocus /></Field>
        ) : null}
        <ProblemBox error={error} />
        <Button variant="primary" busy={busy} type="submit" block>{needCode ? 'Confirm' : 'Sign in'}</Button>
      </form>
    </main>
  );
}
