import { Linking } from 'react-native';
import { router } from 'expo-router';
import { Button, Screen, T } from '@tenmina/ui';
import { SignInForm, pushChoice, portalUrl } from '@tenmina/mobile';

/** Sign in (SCR-PTL-03): email or phone and password, then the authenticator code when MFA is on. */
export default function SignIn() {
  async function next() {
    // SCR-APP-01 is offered once after the first sign-in on this phone.
    router.replace((await pushChoice()) === null ? '/turn-on-notifications' : '/');
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
