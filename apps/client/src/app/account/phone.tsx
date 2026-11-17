import { useState } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, CodeField, Label, Panel, Rise, Screen, T, Tick, haptic } from '@tenmina/ui';
import { Field, ProblemBox, SmsPaused, day, useAction, useSession, type Person } from '@tenmina/mobile';

/**
 * Mobile number and codes by text message (FR-ACC-015). The number receives
 * the code for sign-in and for approvals on the website. A new number needs
 * the password and the code sent to it. After a change, approvals by text
 * message pause for 72 hours and Face ID phones are turned off.
 */
export default function Phone() {
  const { me, reloadMe } = useSession();
  const act = useAction();
  const [changing, setChanging] = useState(false);
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [sentTo, setSentTo] = useState<string>();
  const [code, setCode] = useState('');
  const [done, setDone] = useState(false);

  async function send() {
    const r = await act.run<{ sent_to: string }>('POST', '/v1/me/phone', { phone: phone.replace(/\s+/g, ''), password });
    if (r) {
      setSentTo(r.sent_to);
      setCode('');
    }
  }
  async function confirm() {
    const r = await act.run<Person>('POST', '/v1/me/phone/confirm', { code });
    if (r) {
      haptic('success');
      await reloadMe();
      setDone(true);
      setChanging(false);
      setSentTo(undefined);
      setPassword('');
    }
  }

  const sms = me?.second_factor === 'sms';
  return (
    <Screen
      ground="ink"
      back
      title="Mobile number"
      footer={
        changing ? (
          sentTo ? (
            <Button title="Confirm the new number" icon="checkmark" disabled={code.length < 6} loading={act.busy} onPress={() => void confirm()} />
          ) : (
            <Button title="Send a code to the new number" icon="chatbubble-ellipses-outline" disabled={phone.replace(/\D/g, '').length < 8 || !password} loading={act.busy} onPress={() => void send()} />
          )
        ) : (
          <Button title="Change my number" variant="dark" icon="create-outline" onPress={() => { setChanging(true); act.clear(); }} />
        )
      }
    >
      <Panel style={{ gap: space[2] }}>
        <Label>Your number</Label>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
          {me?.phone_verified ? <Tick size={24} /> : null}
          <T v="title" style={{ flex: 1 }}>{me?.phone_masked || 'No number yet'}</T>
        </View>
        <T v="footnote" muted>
          {me?.phone_verified ? 'Confirmed. ' : 'Not confirmed yet. '}
          {me?.mfa_enabled
            ? 'You use your authenticator app to sign in, so text messages are only for news you choose.'
            : sms
              ? 'We text a code here when you sign in and when you approve on the website.'
              : ''}
        </T>
      </Panel>

      {done ? (
        <Rise>
          <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Tick size={26} />
            <T v="callout" style={{ flex: 1 }}>Your new number is confirmed.</T>
          </Panel>
        </Rise>
      ) : null}

      {me?.sms_pause ? (
        <View style={{ gap: space[2] }}>
          <SmsPaused pause={me.sms_pause} />
          <T v="footnote" muted>{`Until ${day(me.sms_pause.until)}. Face ID approvals were turned off on your phones when the number changed; turn them on again after the pause.`}</T>
        </View>
      ) : null}

      {changing ? (
        <Rise style={{ gap: space[4] }}>
          <Panel style={{ borderWidth: 2, borderColor: brand.orange, backgroundColor: 'transparent', gap: space[2] }}>
            <Label color={brand.orange}>Before you change it</Label>
            <T v="callout">To keep your money safe, approvals by text message pause for 72 hours after a change, and Face ID approvals are turned off on your phones. Payments waiting for you stay at the bank.</T>
          </Panel>
          {sentTo ? (
            <>
              <T v="callout">{`We sent a code to ${sentTo}. It works for 5 minutes.`}</T>
              <CodeField label="Code from the text message" value={code} onChange={setCode} />
              <Button title="Send a new code" variant="quiet" icon="refresh" loading={act.busy} onPress={() => void send()} />
            </>
          ) : (
            <>
              <Field label="New mobile number" value={phone} onChange={setPhone} keyboardType="phone-pad" autoComplete="tel" placeholder="+44 7700 900123" hint="With the country code." />
              <Field label="Your password" value={password} onChange={setPassword} secure autoComplete="password" />
            </>
          )}
          <Button title="Cancel" variant="quiet" onPress={() => { setChanging(false); setSentTo(undefined); act.clear(); }} />
        </Rise>
      ) : null}
      <ProblemBox problem={act.problem} />
      {!changing && me?.mfa_enabled === false ? (
        <Button title="Use an authenticator app instead" variant="quiet" icon="key-outline" onPress={() => router.push('/account/security')} />
      ) : null}
    </Screen>
  );
}
