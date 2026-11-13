'use client';
import { useEffect, useState } from 'react';
import { Button, CodeBoxes, Field, Input, ProblemBox, Select, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, Section, useAction, type Any } from '@/components/kit';

/** SCR-PTL-20: profile, and confirming the phone and email with a one-time code (FR-ACC-001). */
export default function Profile() {
  const { me, refresh } = useSession();
  const a = useAction();
  const [f, setF] = useState<Any>(null);
  useEffect(() => { if (me && !f) setF({ full_name: me.full_name, phone: me.phone, preferred_language: me.preferred_language, residence_country: me.residence_country, preferred_channel: (me as Any).preferred_channel ?? 'email' }); }, [me, f]);
  if (!me || !f) return null;
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Profile" />
      <form className="stack" onSubmit={(e) => { e.preventDefault(); a.run('save', () => a.post('/v1/me', f, 'PATCH'), 'Saved', () => refresh()); }}>
        <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email" hint="To change your email, contact Tenmina."><Input value={me.email} disabled /></Field>
        <Field label="Mobile number"><Input type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
        <Field label="Language"><Select value={f.preferred_language} onChange={(e) => setF({ ...f, preferred_language: e.target.value })}><option value="en">English</option><option value="tw">Twi</option></Select></Field>
        <Field label="Where you live (country code)"><Input value={f.residence_country} maxLength={2} onChange={(e) => setF({ ...f, residence_country: e.target.value.toUpperCase() })} /></Field>
        <Field label="Contact me first by"><Select value={f.preferred_channel} onChange={(e) => setF({ ...f, preferred_channel: e.target.value })}><option value="email">Email</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="push">The app</option></Select></Field>
        <ProblemBox error={a.error} />
        <Button variant="primary" type="submit" busy={a.busy === 'save'}>Save</Button>
      </form>
      <Section title="Confirm your contact details">
        <Confirm channel="phone" identifier={me.phone} done={!!(me as Any).phone_verified} onDone={refresh} />
        <Confirm channel="email" identifier={me.email} done={!!(me as Any).email_verified} onDone={refresh} />
      </Section>
      {a.toast}
    </Ink>
  );
}

function Confirm({ channel, identifier, done, onDone }: { channel: 'phone' | 'email'; identifier: string; done: boolean; onDone: () => void }) {
  const a = useAction();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  if (!identifier) return null;
  return (
    <div className="card stack">
      <div className="spread"><span>{channel === 'phone' ? 'Mobile' : 'Email'}: {identifier}</span>{done ? <Proof>Confirmed</Proof> : null}</div>
      {!done ? (
        sent ? (
          <>
            <span className="muted">Enter the code we sent.</span>
            <CodeBoxes value={code} onChange={setCode} />
            <Button variant="action" disabled={code.length !== 6} busy={a.busy === 'v'} onClick={() => a.run('v', () => a.post('/v1/auth/otp/verify', { identifier, channel, code }), 'Confirmed', onDone)}>Confirm</Button>
            <Button variant="ghost" size="sm" onClick={() => a.run('s', () => a.post('/v1/auth/otp/send', { identifier, channel, purpose: 'signup' }), 'A new code is on its way')}>Send a new code</Button>
          </>
        ) : <Button variant="dark" busy={a.busy === 's'} onClick={() => a.run('s', () => a.post('/v1/auth/otp/send', { identifier, channel, purpose: 'signup' }), 'Code sent', () => setSent(true))}>Send me a code</Button>
      ) : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}
