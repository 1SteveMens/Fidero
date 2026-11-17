import { router, useLocalSearchParams } from 'expo-router';
import { ForgotPasswordScreen } from '@tenmina/mobile';

/** Forgotten password inside the app (SCR-PTL-03, FR-ACC-015): an email code and, for SMS sign-in, a code by text. */
export default function ForgotPassword() {
  const { email, code } = useLocalSearchParams<{ email?: string; code?: string }>();
  return <ForgotPasswordScreen email={email} code={code} onSignIn={() => router.replace('/sign-in')} />;
}
