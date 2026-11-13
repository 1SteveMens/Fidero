'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, CodeBoxes, Field, Input, Mark, ProblemBox, Select, call, useGet, useSession } from '@tenmina/web-ui';

type Any = any; // eslint-disable-line @typescript-eslint/no-explicit-any

const RESIDENCE = [['GB', 'United Kingdom'], ['US', 'United States'], ['CA', 'Canada'], ['DE', 'Germany'], ['NL', 'Netherlands'], ['IT', 'Italy'], ['IE', 'Ireland'], ['AE', 'United Arab Emirates'], ['GH', 'Ghana'], ['NG', 'Nigeria']];

/** W-01 · SCR-PTL-02 and SCR-PTL-37: sign up with email and phone, both confirmed by a one-time code; the privacy notice. */
export default function Register() {
  const { client, refresh } = useSession();
  const router = useRouter();
  const countries = useGet<Any>('/v1/countries');
  const notice = useGet<Any>('/v1/privacy-notices/current');
  const [f, setF] = useState({ full_name: '', email: '', phone: '', password: '', residence_country: 'GB', home_country: 'GH' });
  const [agree, setAgree] = useState(false);
  const [step, setStep] = useState<'form' | 'codes'>('form');
  const [codes, setCodes] = useState({ email: '', phone: '' });
  const [done, setDone] = useState({ email: false, phone: false });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [info, setInfo] = useState('');
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const homes: Any[] = Array.isArray(countries.data) ? countries.data : countries.data?.items ?? [];

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key); setError(null); setInfo('');
    try { await fn(); } catch (e) { setError(e); } finally { setBusy(null); }
  }
  async function signup(e: React.FormEvent) {
    e.preventDefault();
    await run('signup', async () => {
      await call(client, 'GET', '/v1/auth/csrf');
      await call(client, 'POST', '/v1/auth/signup', { ...f, privacy_notice_version: notice.data?.version ?? '' });
      setStep('codes');
    });
  }
  async function verify(channel: 'email' | 'phone') {
    await run(channel, async () => {
      const r = await call<Any>(client, 'POST', '/v1/auth/otp/verify', { identifier: channel === 'email' ? f.email : f.phone, channel, code: codes[channel] });
      setDone({ email: r.email_verified, phone: r.phone_verified });
      if (r.verified) {
        await call(client, 'GET', '/v1/auth/csrf').catch(() => undefined);
        await refresh();
        router.replace('/');
      }
    });
  }
  async function resend(channel: 'email' | 'phone') {
    await run(`re-${channel}`, async () => {
      await call(client, 'POST', '/v1/auth/otp/send', { identifier: channel === 'email' ? f.email : f.phone, channel, purpose: 'signup' });
      setInfo(`A new code is on its way to your ${channel === 'email' ? 'email' : 'phone'}.`);
    });
  }

  return (
    <main className="ground-ink" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      {step === 'form' ? (
        <form onSubmit={signup} className="stack" style={{ width: 'min(460px, 100%)' }}>
          <div className="row"><Mark size={36} /><strong style={{ fontSize: 20 }}>Tenmina</strong></div>
          <h1>Create your account</h1>
          <Field label="Full name"><Input value={f.full_name} onChange={set('full_name')} required autoComplete="name" /></Field>
          <Field label="Email" hint="We send a code to confirm it."><Input type="email" value={f.email} onChange={set('email')} required autoComplete="email" /></Field>
          <Field label="Mobile number" hint="With country code, for example +44 7700 900123. We send a code to confirm it."><Input type="tel" value={f.phone} onChange={set('phone')} required autoComplete="tel" /></Field>
          <Field label="Password" hint="At least 10 characters"><Input type="password" value={f.password} onChange={set('password')} required minLength={10} autoComplete="new-password" /></Field>
          <Field label="Where you live"><Select value={f.residence_country} onChange={set('residence_country')}>{RESIDENCE.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</Select></Field>
          <Field label="The country where things are" hint="This sets the currency and the partner bank."><Select value={f.home_country} onChange={set('home_country')}>{(homes.length ? homes : [{ code: 'GH', name: 'Ghana' }]).map((c: Any) => <option key={c.code} value={c.code}>{c.name}</option>)}</Select></Field>
          {notice.data ? (
            <details className="card" style={{ background: '#1a1a1a' }}>
              <summary style={{ cursor: 'pointer', fontWeight: 700, minHeight: 32 }}>{notice.data.title} (version {notice.data.version})</summary>
              <p style={{ whiteSpace: 'pre-wrap', margin: '8px 0 0' }}>{notice.data.text}</p>
            </details>
          ) : null}
          <label className="row" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} style={{ width: 24, height: 24, flex: 'none', accentColor: '#a3ee5b' }} />
            <span>I have read how Tenmina uses my data.</span>
          </label>
          <ProblemBox error={error} />
          <Button variant="primary" busy={busy === 'signup'} disabled={!agree} type="submit" block>Create account</Button>
          <p className="muted">Already have an account? <Link href="/login">Sign in</Link></p>
        </form>
      ) : (
        <div className="stack" style={{ width: 'min(460px, 100%)' }}>
          <div className="row"><Mark size={36} /><strong style={{ fontSize: 20 }}>Tenmina</strong></div>
          <h1>Confirm your email and phone</h1>
          <p className="muted" style={{ margin: 0 }}>We sent a six-digit code to each. Your account opens once both are confirmed.</p>
          {(['email', 'phone'] as const).map((ch) => (
            <section key={ch} className="card stack" style={{ background: '#1a1a1a' }}>
              <div className="spread"><strong>{ch === 'email' ? f.email : f.phone}</strong>{done[ch] ? <span className="proof">✓ Confirmed</span> : null}</div>
              {!done[ch] ? <>
                <CodeBoxes value={codes[ch]} onChange={(v) => setCodes({ ...codes, [ch]: v })} autoFocus={ch === 'email'} />
                <Button variant="primary" disabled={codes[ch].length !== 6} busy={busy === ch} onClick={() => verify(ch)}>Confirm {ch === 'email' ? 'email' : 'phone'}</Button>
                <Button variant="ghost" size="sm" busy={busy === `re-${ch}`} onClick={() => resend(ch)}>Send a new code</Button>
              </> : null}
            </section>
          ))}
          {info ? <p className="muted" role="status">{info}</p> : null}
          <ProblemBox error={error} />
          {done.email && done.phone ? <Link className="btn btn-primary" href="/login">Sign in</Link> : null}
        </div>
      )}
    </main>
  );
}
