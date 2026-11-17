import { router } from 'expo-router';
import { Button, Screen, T } from '@tenmina/ui';
import { SignInForm, pushChoice } from '@tenmina/mobile';

/**
 * Sign in (SCR-PTL-03): email or phone and password, then the second factor:
 * the code we text to the confirmed number (FR-ACC-015), or the authenticator
 * code for a client who set one up. Then, once, Face ID for approvals.
 * Forgotten password and help stay in the app.
 */
export default function SignIn() {
  async function next() {
    // Face ID for approvals (FR-ACC-014), then SCR-APP-01: each offered once on this phone.
    const after = (await pushChoice()) === null ? '/turn-on-notifications' : '/';
    router.replace({ pathname: '/face-id', params: { next: after } });
  }
  return (
    <Screen ground="ink" back title="Sign in">
      <T v="callout" muted>Use the email address or mobile number you signed up with.</T>
      <SignInForm
        onSignedIn={() => void next()}
        footer={
          <>
            <Button title="Forgot your password?" variant="quiet" onPress={() => router.push('/forgot-password')} />
            <Button title="Get help" variant="quiet" icon="help-circle-outline" onPress={() => router.push('/help')} />
          </>
        }
      />
    </Screen>
  );
}
