import { ScrollView, View } from 'react-native';
import { Redirect, router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, font, space } from '@tenmina/tokens';
import { Button, GroundContext, Label, Mark, Panel, Rise, T } from '@tenmina/ui';
import { ProblemBox, SignInForm, useSession } from '@tenmina/mobile';
import { useField } from '../store';

/**
 * Sign in and register this phone (SCR-MOB-01; FR-MOB-001, FR-MOB-004). After
 * sign-in the phone makes its signing key and registers it with the server's
 * challenge and the platform's attestation. A copy that fails the check is told plainly.
 */
export default function Welcome() {
  const { status, me, signOut } = useSession();
  const { device, registerDevice, registering, registerProblem } = useField();
  const insets = useSafeAreaInsets();
  if (status === 'signedIn' && device) return <Redirect href="/" />;
  const failed = registerProblem?.code === 'attestation-failed';

  return (
    <GroundContext.Provider value="ink">
      <ScrollView style={{ flex: 1, backgroundColor: brand.ink }} contentContainerStyle={{ flexGrow: 1, paddingTop: insets.top + space[4], paddingBottom: insets.bottom + space[4], paddingHorizontal: space[6], gap: space[5] }}>
        <Rise style={{ flexDirection: 'row', alignItems: 'baseline', gap: space[2] }}>
          <Mark />
          <T v="title" color="#F7F6F2" style={{ fontFamily: font.heavy, letterSpacing: -1 }}>tenmina</T>
          <Label color={brand.lime}>Field</Label>
        </Rise>
        <View style={{ flex: 1, justifyContent: 'center', gap: space[4] }}>
          <Rise delay={100}>
            <T v="display" header color="#F7F6F2">{status === 'signedIn' ? 'Register this phone.' : 'Work you can prove.'}</T>
          </Rise>
          {status !== 'signedIn' ? (
            <>
              <Rise delay={180}>
                <T v="body" muted>Your jobs, checklists and evidence in one place. Photos are taken in this app only, and sealed when they are taken.</T>
              </Rise>
              <Rise delay={240}>
                <SignInForm onSignedIn={() => void registerDevice()} />
              </Rise>
            </>
          ) : (
            <Rise delay={180} style={{ gap: space[4] }}>
              <T v="body" muted>{`Signed in as ${me?.full_name ?? ''}. This phone makes its own key to seal your photos and check-ins. Tenmina checks that this copy of the app is genuine.`}</T>
              {failed ? (
                <Panel style={{ borderWidth: 2, borderColor: brand.orange, backgroundColor: 'transparent' }}>
                  <Ionicons name="close-circle" size={24} color={brand.orange} />
                  <T v="headline">This copy of Tenmina Field cannot be used.</T>
                  <T v="callout" muted>Install it from Google Play or the App Store, then sign in again.</T>
                </Panel>
              ) : (
                <ProblemBox problem={registerProblem} />
              )}
              <Button title={registerProblem ? 'Try again' : 'Register this phone'} icon="phone-portrait-outline" loading={registering} onPress={() => void registerDevice().then(() => router.replace('/'))} />
              <Button title="Sign out" variant="quiet" onPress={() => void signOut()} />
            </Rise>
          )}
        </View>
      </ScrollView>
    </GroundContext.Provider>
  );
}
