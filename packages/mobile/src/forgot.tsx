import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Button, CodeField, Panel, Rise, Screen, T, Tick, haptic } from '@tenmina/ui';
import { Field, ProblemBox } from './components';
import { useAction } from './hooks';

/**
 * Forgotten password, inside the app (SCR-PTL-03, FR-ACC-002, FR-ACC-015).
 * Step 1: the email address. Tenmina sends a code to the email and, for a
 * client who uses codes by text message, a second code to the phone: a reset
 * needs both, so a stolen SIM alone never takes over the account. Step 2: the
 * codes and a new password. A link from the email can open this screen with
 * `email` and `code` filled in. Shared by both apps.
 */
export function ForgotPasswordScreen({ email: startEmail, code: startCode, onSignIn }: { email?: string; code?: string; onSignIn: () => void }) {
  const params = { email: startEmail, code: startCode };
  const act = useAction();
  const [email, setEmail] = useState(params.email ?? '');
  const [sent, setSent] = useState(!!params.code);
  const [emailCode, setEmailCode] = useState(params.code ?? '');
  const [smsCode, setSmsCode] = useState('');
  const [password, setPassword] = useState('');
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (params.code) setEmailCode(params.code);
  }, [params.code]);

  async function send() {
    const r = await act.run('POST', '/v1/auth/password-reset', { identifier: email.trim(), channel: 'email' }, { anonymous: true });
    if (r) setSent(true);
  }
  async function reset() {
    const r = await act.run('POST', '/v1/auth/password-reset/confirm', { identifier: email.trim(), channel: 'email', code: emailCode, sms_code: smsCode, new_password: password }, { anonymous: true });
    if (r) {
      haptic('success');
      setDone(true);
    }
  }

  if (done) {
    return (
      <Screen ground="ink" footer={<Button title="Sign in" icon="arrow-forward" onPress={onSignIn} />}>
        <View style={{ paddingTop: space[7], gap: space[4] }}>
          <Tick size={56} />
          <T v="display" header>Your password is changed.</T>
          <T v="body" muted>Sign in with the new password. For your safety, Face ID approvals were turned off on your phones; turn them on again after you sign in.</T>
        </View>
      </Screen>
    );
  }

  const strong = password.length >= 10;
  return (
    <Screen
      ground="ink"
      back
      title="Forgot your password"
      footer={
        sent ? (
          <Button title="Change my password" icon="checkmark" disabled={emailCode.length < 6 || !strong} loading={act.busy} onPress={() => void reset()} />
        ) : (
          <Button title="Send the codes" icon="mail-outline" disabled={!email.includes('@')} loading={act.busy} onPress={() => void send()} />
        )
      }
    >
      {!sent ? (
        <>
          <T v="callout" muted>Enter the email address you signed up with. We send a code to it and, if you sign in with codes by text message, one to your phone as well.</T>
          <Field label="Email address" value={email} onChange={setEmail} keyboardType="email-address" autoComplete="email" placeholder="you@example.com" />
        </>
      ) : (
        <Rise style={{ gap: space[4] }}>
          <Panel>
            <T v="callout">{`If ${email.trim() || 'the address'} has a Tenmina account, we sent a code to it. If you sign in with codes by text message, we also texted a code to your phone. Each works for a few minutes.`}</T>
          </Panel>
          <CodeField label="Code from the email" value={emailCode} onChange={setEmailCode} />
          <CodeField label="Code from the text message (if you got one)" value={smsCode} onChange={setSmsCode} />
          <Field label="New password" value={password} onChange={setPassword} secure autoComplete="password" hint="At least 10 characters." />
          <Button title="Send the codes again" variant="quiet" icon="refresh" loading={act.busy} onPress={() => void send()} />
          <T v="footnote" muted>Do not share these codes. Tenmina will never call you for them.</T>
        </Rise>
      )}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
