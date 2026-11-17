'use client';
import { useEffect, useState } from 'react';
import { Button, CodeBoxes, Field, Input, ProblemBox, Select, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Proof, Section, useAction, type Any } from '@/components/kit';
import { SmsPausedCard, useMeFactor } from '@/components/secondfactor';

/** SCR-PTL-20: profile, confirming the phone and email with a one-time code (FR-ACC-001), and changing the mobile number (FR-ACC-015). */
export default function Profile() {
  const { me, refresh } = useSession();
  const a = useAction();
  const [f, setF] = useState<Any>(null);
  useEffect(() => { if (me && !f) setF({ full_name: me.full_name, preferred_language: me.preferred_language, residence_country: me.residence_country, preferred_channel: (me as Any).preferred_channel ?? 'email' }); }, [me, f]);
  if (!me || !f) return null;
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Profile" />
      <form className="stack" onSubmit={(e) => { e.preventDefault(); a.run('save', () => a.post('/v1/me', f, 'PATCH'), 'Saved', () => refresh()); }}>
        <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email" hint="To change your email, contact Tenmina."><Input value={me.email} disabled /></Field>
        <Field label="Language"><Select value={f.preferred_language} onChange={(e) => setF({ ...f, preferred_language: e.target.value })}><option value="en">English</option><option value="tw">Twi</option></Select></Field>
        <Field label="Where you live (country code)"><Input value={f.residence_country} maxLength={2} onChange={(e) => setF({ ...f, residence_country: e.target.value.toUpperCase() })} /></Field>
        <Field label="Contact me first by"><Select value={f.preferred_channel} onChange={(e) => setF({ ...f, preferred_channel: e.target.value })}><option value="email">Email</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="push">The app</option></Select></Field>
        <ProblemBox error={a.error} />
        <Button variant="primary" type="submit" busy={a.busy === 'save'}>Save</Button>
      </form>
      <PhoneChange onDone={refresh} />
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

/**
 * A new mobile number (FR-ACC-015): the password, then the code sent to the new
 * number. Approvals by text message then pause for 72 hours and Face ID phones
 * are turned off; the pause and its reason show here.
 */
function PhoneChange({ onDone }: { onDone: () => void }) {
  const mf = useMeFactor();
  const a = useAction();
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const send = () => a.run('ps', () => a.post('/v1/me/phone', { phone: phone.replace(/\s+/g, ''), password }), undefined, (r: Any) => { setSentTo(r.sent_to); setCode(''); });
  return (
    <Section title="Mobile number">
      <div className="card stack">
        <div className="spread"><span className="mono">{mf?.phone_masked || 'No number yet'}</span>{mf && (mf as Any).phone_verified ? <Proof>Confirmed</Proof> : null}</div>
        {mf?.sms_pause ? <SmsPausedCard pause={mf.sms_pause} /> : null}
        {!open ? (
          <Button variant="ghost" onClick={() => { setOpen(true); setSentTo(null); }}>Change my number</Button>
        ) : sentTo ? (
          <>
            <span>We sent a code to <strong className="mono">{sentTo}</strong>. It works for 5 minutes.</span>
            <CodeBoxes value={code} onChange={setCode} autoFocus />
            <Button variant="action" disabled={code.length !== 6} busy={a.busy === 'pc'} onClick={() => a.run('pc', () => a.post('/v1/me/phone/confirm', { code }), 'Your new number is confirmed', () => { setOpen(false); setSentTo(null); setPassword(''); onDone(); })}>Confirm the new number</Button>
            <Button variant="ghost" size="sm" busy={a.busy === 'ps'} onClick={send}>Send a new code</Button>
          </>
        ) : (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <p className="muted" style={{ margin: 0 }}>To keep your money safe, approvals by text message pause for 72 hours after a change, and Face ID approvals are turned off on your phones.</p>
            <Field label="New mobile number" hint="With the country code, for example +44 7700 900123"><Input type="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required /></Field>
            <Field label="Your password"><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
            <Button variant="dark" type="submit" busy={a.busy === 'ps'}>Send a code to the new number</Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => setOpen(false)}>Cancel</Button>
          </form>
        )}
        <ProblemBox error={a.error} />
      </div>
      {a.toast}
    </Section>
  );
}
