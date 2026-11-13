'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, Mark, ProblemBox, Select, call, useSession } from '@tenmina/web-ui';

export default function Register() {
  const { client, refresh } = useSession();
  const router = useRouter();
  const [f, setF] = useState({ full_name: '', email: '', phone: '', password: '', residence_country: 'GB', home_country: 'GH' });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await call(client, 'GET', '/v1/auth/csrf');
      await call(client, 'POST', '/v1/auth/register', f);
      await refresh();
      router.replace('/');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="ground-ink" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form onSubmit={submit} className="stack" style={{ width: 'min(460px, 100%)' }}>
        <div className="row"><Mark size={36} /><strong style={{ fontSize: 20 }}>Tenmina</strong></div>
        <h1>Create your account</h1>
        <Field label="Full name"><Input value={f.full_name} onChange={set('full_name')} required autoComplete="name" /></Field>
        <Field label="Email"><Input type="email" value={f.email} onChange={set('email')} required autoComplete="email" /></Field>
        <Field label="Mobile number" hint="With country code, for example +44 7700 900123"><Input type="tel" value={f.phone} onChange={set('phone')} autoComplete="tel" /></Field>
        <Field label="Password" hint="At least 10 characters"><Input type="password" value={f.password} onChange={set('password')} required minLength={10} autoComplete="new-password" /></Field>
        <Field label="Where you live">
          <Select value={f.residence_country} onChange={set('residence_country')}>
            {[['GB', 'United Kingdom'], ['US', 'United States'], ['CA', 'Canada'], ['DE', 'Germany'], ['NL', 'Netherlands'], ['IT', 'Italy'], ['AE', 'United Arab Emirates'], ['GH', 'Ghana'], ['NG', 'Nigeria']].map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </Select>
        </Field>
        <Field label="Home country"><Select value={f.home_country} onChange={set('home_country')}><option value="GH">Ghana</option></Select></Field>
        <ProblemBox error={error} />
        <Button variant="primary" busy={busy} type="submit" block>Create account</Button>
        <p className="muted">Already have an account? <Link href="/login">Sign in</Link></p>
      </form>
    </main>
  );
}
