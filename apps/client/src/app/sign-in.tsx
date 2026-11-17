import { Linking } from 'react-native';
import { router } from 'expo-router';
import { Button, Screen, T } from '@tenmina/ui';
import { SignInForm, pushChoice, portalUrl } from '@tenmina/mobile';

/** Sign in (SCR-PTL-03): email or phone and password, then the authenticator code when MFA is on. Then, once, Face ID for approvals. */
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
        footer={<Button title="Forgot your password?" variant="quiet" onPress={() => void Linking.openURL(`${portalUrl()}/password-reset`)} />}
      />
    </Screen>
  );
}
