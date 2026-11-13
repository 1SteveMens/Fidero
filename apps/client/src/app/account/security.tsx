import { useState } from 'react';
import { Linking, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, CodeField, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { ProblemBox, useAction, useSession } from '@tenmina/mobile';

/**
 * Authenticator app (FR-ACC-003). Every approval needs its 6-digit code, so a
 * client sets it up once: add the key to an authenticator app, then enter a code.
 */
export default function Security() {
  const { me, reloadMe } = useSession();
  const act = useAction();
  const [setup, setSetup] = useState<{ otpauth_uri: string; secret: string }>();
  const [code, setCode] = useState('');
  const [done, setDone] = useState(false);

  async function start() {
    const r = await act.run<{ otpauth_uri: string; secret: string }>('POST', '/v1/auth/mfa/setup');
    if (r) setSetup(r);
  }
  async function confirm() {
    const r = await act.run('POST', '/v1/auth/mfa/confirm', { code });
    if (r) {
      await reloadMe();
      setDone(true);
    }
  }

  if (me?.mfa_enabled || done) {
    return (
      <Screen ground="ink" back title="Authenticator app" footer={<Button title="Done" onPress={() => router.back()} />}>
        <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Tick size={28} />
          <T v="headline" style={{ flex: 1 }}>Your authenticator is set up.</T>
        </Panel>
        <T v="callout" muted>Each approval asks for its 6-digit code. If you lose the phone with the authenticator, contact Tenmina: we check who you are before resetting it.</T>
      </Screen>
    );
  }

  return (
    <Screen
      ground="ink"
      back
      title="Set up your authenticator"
      footer={
        setup ? (
          <Button title="Confirm" icon="checkmark" disabled={code.length < 6} loading={act.busy} onPress={() => void confirm()} />
        ) : (
          <Button title="Start" icon="key-outline" loading={act.busy} onPress={() => void start()} />
        )
      }
    >
      <T v="callout" muted>Use an authenticator app such as Google Authenticator, Microsoft Authenticator or 1Password. Approving a payment always needs its code, even with Face ID.</T>
      {setup ? (
        <>
          <Panel>
            <Label>1 · Add Tenmina to the authenticator</Label>
            <Button title="Open the authenticator app" variant="dark" icon="open-outline" onPress={() => void Linking.openURL(setup.otpauth_uri)} />
            <T v="footnote" muted>Or type this key into it:</T>
            <View style={{ backgroundColor: '#242424', borderRadius: 12, padding: space[3] }}>
              <T v="mono" color={brand.lime} style={{ fontSize: 15, letterSpacing: 1.5 }}>{setup.secret.replace(/(.{4})/g, '$1 ').trim()}</T>
            </View>
          </Panel>
          <Panel>
            <Label>2 · Enter the code it shows</Label>
            <CodeField label="6-digit code" value={code} onChange={setCode} />
          </Panel>
        </>
      ) : (
        <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Ionicons name="shield-checkmark-outline" size={22} color={brand.lime} />
          <T v="callout" style={{ flex: 1 }}>It takes about a minute.</T>
        </Panel>
      )}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
