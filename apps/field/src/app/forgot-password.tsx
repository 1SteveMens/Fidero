import { router, useLocalSearchParams } from 'expo-router';
import { ForgotPasswordScreen } from '@tenmina/mobile';

/** Forgotten password inside Tenmina Field: a code by email, then a new password. */
export default function ForgotPassword() {
  const { email, code } = useLocalSearchParams<{ email?: string; code?: string }>();
  return <ForgotPasswordScreen email={email} code={code} onSignIn={() => router.replace('/welcome')} />;
}
