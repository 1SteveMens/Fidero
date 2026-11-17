import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Button, CodeField, Rise, T, haptic } from '@tenmina/ui';
import { ProblemBox, SmsPaused, biometricSupport, enrolApprovalKey, toProblem, useApi, useSession, type BiometricSupport, type Problem } from '@tenmina/mobile';

/**
 * Turn on Face ID or a fingerprint for approvals on this phone (FR-ACC-014).
 * The phone makes a key and Tenmina registers only its public half, with one
 * code: the one entered at sign-in if it was in the last 5 minutes, otherwise
 * the authenticator code, or for a client without one a code sent by SMS
 * (FR-ACC-015). While SMS approvals are paused, an SMS code cannot do it.
 */
export function EnrolBiometric({ onDone, onSkip, skipLabel = 'Not now' }: { onDone: () => void; onSkip?: () => void; skipLabel?: string }) {
  const api = useApi();
  const { me } = useSession();
  const [support, setSupport] = useState<BiometricSupport>();
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState('');
  const [sentTo, setSentTo] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();
  const sms = !!me && !me.mfa_enabled && me.second_factor === 'sms';

  useEffect(() => {
    void biometricSupport().then(setSupport);
  }, []);

  async function send() {
    setBusy(true);
    setProblem(undefined);
    try {
      const r = await api.post<{ sent_to: string }>('/v1/auth/mfa/sms');
      setSentTo(r.sent_to);
      setCode('');
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

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
  if (sms && me?.sms_pause) {
    return (
      <View style={{ gap: space[3] }}>
        <SmsPaused pause={me.sms_pause} />
        {onSkip ? <Button title={skipLabel} variant="quiet" onPress={onSkip} /> : null}
      </View>
    );
  }
  const waitingForSms = needsCode && sms && !sentTo;
  return (
    <View style={{ gap: space[3] }}>
      {needsCode ? (
        <Rise style={{ gap: space[2] }}>
          {sms ? (
            sentTo ? (
              <>
                <T v="callout">{`We sent a code to ${sentTo}. Enter it to turn on ${support.label}.`}</T>
                <CodeField label="Code from the text message" value={code} onChange={setCode} />
                <Button title="Send a new code" variant="quiet" icon="refresh" disabled={busy} onPress={() => void send()} />
              </>
            ) : (
              <>
                <T v="callout">{`To turn on ${support.label}, confirm it is you with a code we text to ${me?.phone_masked || 'your phone'}.`}</T>
                <Button title="Send me a code" variant="dark" icon="chatbubble-ellipses-outline" loading={busy} onPress={() => void send()} />
              </>
            )
          ) : (
            <>
              <T v="callout">{`Enter the code from your authenticator app once to turn on ${support.label}.`}</T>
              <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
            </>
          )}
        </Rise>
      ) : null}
      <ProblemBox problem={problem} />
      {waitingForSms ? null : (
        <Button
          title={`Use ${support.label} for approvals`}
          icon={support.label === 'Face ID' || support.label === 'face unlock' ? 'scan-outline' : 'finger-print'}
          disabled={needsCode && code.length < 6}
          loading={busy}
          onPress={() => void turnOn()}
        />
      )}
      {onSkip ? <Button title={skipLabel} variant="quiet" onPress={onSkip} /> : null}
      <T v="footnote" muted>Your face or fingerprint never leaves this phone. Tenmina keeps only a key that proves the approval came from this phone.</T>
    </View>
  );
}
