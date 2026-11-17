import { useEffect, useState } from 'react';
import { Linking, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, CodeField, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { ProblemBox, localApprovalKey, useAction, useSession } from '@tenmina/mobile';
import { EnrolBiometric } from '../../components/EnrolBiometric';

/**
 * Authenticator app (FR-ACC-003). Every approval needs a second factor, so a
 * client sets it up once: add the key to an authenticator app, then enter a
 * code. Then this phone can use Face ID or a fingerprint instead of typing the
 * code at each approval (FR-ACC-014).
 */
export default function Security() {
  const { me, reloadMe } = useSession();
  const act = useAction();
  const [setup, setSetup] = useState<{ otpauth_uri: string; secret: string }>();
  const [code, setCode] = useState('');
  const [done, setDone] = useState(false);
  const [biometricOn, setBiometricOn] = useState(false);
  useEffect(() => {
    if (me) void localApprovalKey(me.id).then((k) => setBiometricOn(!!k));
  }, [me]);

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
        <T v="callout" muted>Each approval asks for its 6-digit code, or Face ID or a fingerprint on a phone where you turn it on. If you lose the phone with the authenticator, contact Tenmina: we check who you are before resetting it.</T>
        <Panel>
          <Label>Face ID or fingerprint for approvals</Label>
          {biometricOn ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <Tick size={24} />
              <T v="callout" style={{ flex: 1 }}>On for this phone.</T>
            </View>
          ) : (
            <EnrolBiometric onDone={() => setBiometricOn(true)} />
          )}
          <Button title="Phones that can approve" variant="dark" icon="phone-portrait-outline" onPress={() => router.push('/account/approval-keys')} />
        </Panel>
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
      <T v="callout" muted>Use an authenticator app such as Google Authenticator, Microsoft Authenticator or 1Password. Approving a payment needs its code, or Face ID or a fingerprint once you turn that on for this phone.</T>
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
