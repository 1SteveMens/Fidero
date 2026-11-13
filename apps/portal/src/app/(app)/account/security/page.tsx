'use client';
import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Button, CodeBoxes, Field, Input, ProblemBox, useSession } from '@tenmina/web-ui';
import { Copy, Ink, PageHead, Proof, Section, useAction, type Any } from '@/components/kit';

/** FR-ACC-003: the authenticator app (scan the QR code, confirm a code) and the password. */
export default function Security() {
  const { me, refresh } = useSession();
  const a = useAction();
  const [setup, setSetup] = useState<Any>(null);
  const [qr, setQr] = useState('');
  const [code, setCode] = useState('');
  const [pw, setPw] = useState({ old_password: '', new_password: '' });
  const [off, setOff] = useState('');
  useEffect(() => {
    if (!setup?.otpauth_uri) return;
    QRCode.toDataURL(setup.otpauth_uri, { margin: 1, width: 220, color: { dark: '#0b0b0b', light: '#ffffff' } }).then(setQr).catch(() => setQr(''));
  }, [setup]);
  if (!me) return null;
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Sign-in and approvals" />
      <Section title="Authenticator app">
        {me.mfa_enabled ? (
          <div className="card stack">
            <Proof>On. Every money approval asks for its code.</Proof>
            <span className="muted" style={{ fontSize: 14 }}>To switch it off, enter a current code. You will not be able to approve payments until you set it up again.</span>
            <CodeBoxes value={off} onChange={setOff} />
            <Button variant="ghost" disabled={off.length !== 6} busy={a.busy === 'off'} onClick={() => a.run('off', () => a.post('/v1/auth/mfa/disable', { code: off }), 'Switched off', () => refresh())}>Switch it off</Button>
          </div>
        ) : !setup ? (
          <div className="card stack">
            <span>Use an authenticator app such as Google Authenticator or Microsoft Authenticator. You need it to approve any payment.</span>
            <Button variant="primary" busy={a.busy === 'setup'} onClick={() => a.run('setup', () => a.post('/v1/auth/mfa/setup'), undefined, (r) => { setSetup(r); setCode(''); })}>Set up the app</Button>
          </div>
        ) : (
          <div className="card stack">
            <span>1. Scan this code with the app.</span>
            {qr ? <img src={qr} alt="QR code for your authenticator app" width={220} height={220} style={{ background: '#fff', borderRadius: 12, padding: 8, alignSelf: 'center' }} /> : null}
            <span className="muted" style={{ fontSize: 14 }}>Or type this key:</span>
            <div className="row"><span className="mono" style={{ overflowWrap: 'anywhere' }}>{setup.secret}</span><Copy value={setup.secret} /></div>
            <span>2. Enter the six-digit code the app shows.</span>
            <CodeBoxes value={code} onChange={setCode} />
            <Button variant="primary" disabled={code.length !== 6} busy={a.busy === 'confirm'} onClick={() => a.run('confirm', () => a.post('/v1/auth/mfa/confirm', { code }), 'Your authenticator app is on', () => { setSetup(null); refresh(); })}>Turn it on</Button>
          </div>
        )}
      </Section>
      <Section title="Password">
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('pw', () => a.post('/v1/auth/password', pw), 'Password changed', () => setPw({ old_password: '', new_password: '' })); }}>
          <Field label="Current password"><Input type="password" autoComplete="current-password" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} required /></Field>
          <Field label="New password" hint="At least 10 characters"><Input type="password" autoComplete="new-password" minLength={10} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required /></Field>
          <Button variant="dark" type="submit" busy={a.busy === 'pw'}>Change password</Button>
        </form>
      </Section>
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
