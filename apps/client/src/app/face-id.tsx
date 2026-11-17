import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Panel, Screen, T } from '@tenmina/ui';
import { biometricOffered, biometricSupport, localApprovalKey, markBiometricOffered, useSession, type BiometricSupport } from '@tenmina/mobile';
import { EnrolBiometric } from '../components/EnrolBiometric';

const ABOUT = [
  ['hand-left-outline', 'Press and hold to approve, then look at the phone or touch the sensor'],
  ['shield-checkmark-outline', 'Still two checks: something you know to sign in, and this phone with your face or finger'],
  ['key-outline', 'The authenticator code stays as the back-up, and the website keeps using it'],
] as const;

/**
 * Offered once after sign-in (FR-ACC-014): "Use Face ID for approvals", or
 * "fingerprint" on Android. A person with no authenticator yet is sent to set
 * one up first. Anything else (a browser, no biometric, already on, already
 * offered) goes straight on to `next`.
 */
export default function FaceIdOffer() {
  const { me } = useSession();
  const { next } = useLocalSearchParams<{ next?: string }>();
  const [support, setSupport] = useState<BiometricSupport>();
  const go = () => router.replace((next || '/') as never);

  useEffect(() => {
    if (!me) return;
    void (async () => {
      const s = await biometricSupport();
      if (!s.available || (await localApprovalKey(me.id)) || (await biometricOffered(me.id))) {
        router.replace((next || '/') as never);
        return;
      }
      setSupport(s);
    })();
  }, [me, next]);

  if (!me || !support) return <Screen ground="ink"><View /></Screen>;

  async function skip() {
    if (me) await markBiometricOffered(me.id, 'not_now');
    go();
  }

  return (
    <Screen ground="ink">
      <View style={{ paddingTop: space[7], gap: space[4] }}>
        <View style={{ width: 72, height: 72, borderRadius: 22, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={support.label === 'Face ID' || support.label === 'face unlock' ? 'scan-outline' : 'finger-print'} size={36} color={brand.ink} />
        </View>
        <T v="display" header>{`Use ${support.label} for approvals`}</T>
        <T v="body" muted>{`Approve payments with ${support.label} instead of typing the code from your authenticator app each time.`}</T>
        <Panel style={{ gap: space[3] }}>
          {ABOUT.map(([icon, text]) => (
            <View key={text} style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
              <Ionicons name={icon} size={22} color={brand.lime} />
              <T v="callout" style={{ flex: 1 }}>{text}</T>
            </View>
          ))}
        </Panel>
        {me.mfa_enabled ? (
          <EnrolBiometric onDone={go} onSkip={() => void skip()} />
        ) : (
          <View style={{ gap: space[3] }}>
            <T v="callout">Approvals need an authenticator app first. Set it up now; then you can turn on {support.label}.</T>
            <Button
              title="Set up the authenticator"
              icon="key-outline"
              onPress={() => {
                void markBiometricOffered(me.id, 'not_now').then(() => router.replace('/account/security'));
              }}
            />
            <Button title="Not now" variant="quiet" onPress={() => void skip()} />
          </View>
        )}
      </View>
    </Screen>
  );
}
