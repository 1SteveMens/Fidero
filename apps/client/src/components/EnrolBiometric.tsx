import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Button, CodeField, Rise, T, haptic } from '@tenmina/ui';
import { ProblemBox, biometricSupport, enrolApprovalKey, useApi, useSession, type BiometricSupport, type Problem } from '@tenmina/mobile';

/**
 * Turn on Face ID or a fingerprint for approvals on this phone (FR-ACC-014).
 * The phone makes a key and Tenmina registers only its public half, with the
 * authenticator code once: the one entered at sign-in if it was in the last 5
 * minutes, otherwise the six boxes show.
 */
export function EnrolBiometric({ onDone, onSkip, skipLabel = 'Not now' }: { onDone: () => void; onSkip?: () => void; skipLabel?: string }) {
  const api = useApi();
  const { me } = useSession();
  const [support, setSupport] = useState<BiometricSupport>();
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();

  useEffect(() => {
    void biometricSupport().then(setSupport);
  }, []);

  async function turnOn() {
    if (!me || !support) return;
    setBusy(true);
    setProblem(undefined);
    const r = await enrolApprovalKey(api, me.id, support.label, needsCode ? code : undefined);
    setBusy(false);
    if (r.ok) {
      haptic('success');
      onDone();
      return;
    }
    if (r.needsCode) {
      setNeedsCode(true);
      setCode('');
    }
    setProblem(r.problem);
  }

  if (!support) return null;
  if (!support.available) {
    return (
      <View style={{ gap: space[3] }}>
        <T v="callout" muted>{support.reason}</T>
        {onSkip ? <Button title="Continue" variant="dark" onPress={onSkip} /> : null}
      </View>
    );
  }
  return (
    <View style={{ gap: space[3] }}>
      {needsCode ? (
        <Rise style={{ gap: space[2] }}>
          <T v="callout">{`Enter the code from your authenticator app once to turn on ${support.label}.`}</T>
          <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
        </Rise>
      ) : null}
      <ProblemBox problem={problem} />
      <Button
        title={`Use ${support.label} for approvals`}
        icon={support.label === 'Face ID' || support.label === 'face unlock' ? 'scan-outline' : 'finger-print'}
        disabled={needsCode && code.length < 6}
        loading={busy}
        onPress={() => void turnOn()}
      />
      {onSkip ? <Button title={skipLabel} variant="quiet" onPress={onSkip} /> : null}
      <T v="footnote" muted>Your face or fingerprint never leaves this phone. Tenmina keeps only a key that proves the approval came from this phone.</T>
    </View>
  );
}
