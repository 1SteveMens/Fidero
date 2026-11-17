import { useCallback, useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { Button, CodeField, Label, T, usePalette } from '@tenmina/ui';
import { toProblem, type Problem } from './api';
import { biometricStepUp, biometricSupport, localApprovalKey, type BiometricLabel } from './biometric';
import { useSession, type Person, type SmsPause } from './session';

/** After this many cancelled Face ID prompts the approval falls back to the code (FR-ACC-014). */
export const MAX_BIOMETRIC_CANCELS = 3;

/**
 * "biometric": Face ID or fingerprint after the hold. "code": the authenticator's six boxes.
 * "sms": send a code by SMS, then six boxes (FR-ACC-015). "paused": SMS approvals are paused.
 * "none": no second factor yet (no authenticator and no confirmed number).
 */
export type FactorMode = 'loading' | 'biometric' | 'code' | 'sms' | 'paused' | 'none';

export type ApprovalMethod = 'device_biometric' | 'totp' | 'sms_code';

export type ConfirmResult =
  /** `code` is the authenticator code to send with the action; empty when a step-up already happened (Face ID or SMS). */
  | { ok: true; code: string; method: ApprovalMethod }
  | { ok: false; problem?: Problem; cancelled?: boolean };

export interface SecondFactor {
  mode: FactorMode;
  /** What the code boxes stand for when Face ID is not used: the authenticator, SMS, or SMS paused. */
  fallback: 'code' | 'sms' | 'paused' | 'none';
  label: BiometricLabel;
  /** Why the code boxes show although this phone had Face ID turned on. */
  note?: string;
  code: string;
  setCode: (v: string) => void;
  /** SMS: where the code went once sent, e.g. "+44 •••• 123". */
  sentTo?: string;
  sending: boolean;
  /** SMS: ask Tenmina to text a code (POST /v1/auth/mfa/sms). */
  send: () => Promise<void>;
  /** A problem from sending the SMS code. */
  sendProblem?: Problem;
  /** Why SMS approvals are paused, when they are. */
  pause?: SmsPause | null;
  /** The masked number SMS codes go to. */
  phone?: string;
  /** True when the hold button may start: Face ID is ready, or six digits are in. */
  ready: boolean;
  /** Run the second factor. With `stepUp` an authenticator code is sent to /v1/auth/mfa/step-up here too. An SMS code always is. */
  confirm: (opts?: { stepUp?: boolean }) => Promise<ConfirmResult>;
  /** Show the code instead of Face ID. */
  switchToCode: () => void;
  /** Clear the code after a failed try. */
  reset: () => void;
}

/** The second factor a person uses when Face ID is not in play (FR-ACC-003, FR-ACC-015). */
export function fallbackOf(me: Pick<Person, 'mfa_enabled' | 'second_factor' | 'sms_pause'>): SecondFactor['fallback'] {
  if (me.mfa_enabled || me.second_factor === 'authenticator') return 'code';
  if (me.second_factor === 'sms') return me.sms_pause ? 'paused' : 'sms';
  return 'none';
}

/** How an approval was confirmed, in words for the "You approved" line. */
export function methodWords(method: ApprovalMethod, label: BiometricLabel): string {
  if (method === 'device_biometric') return label;
  if (method === 'sms_code') return 'a code by text message';
  return 'your authenticator code';
}

/**
 * The second factor for one approval (FR-ACC-003, FR-ACC-014, FR-ACC-015):
 * Face ID or a fingerprint where this phone has an approval key; otherwise the
 * authenticator code if the client set one up, else a code sent by SMS. Three
 * cancelled prompts, a revoked key or no biometric on the phone fall back to
 * the code. SMS approvals pause for 72 hours after a number change or a
 * reported SIM swap; the screen says why.
 */
export function useSecondFactor(): SecondFactor {
  const { api, me, reloadMe } = useSession();
  const [mode, setMode] = useState<FactorMode>('loading');
  const [label, setLabel] = useState<BiometricLabel>('Face ID');
  const [note, setNote] = useState<string>();
  const [code, setCode] = useState('');
  const [cancels, setCancels] = useState(0);
  const [sentTo, setSentTo] = useState<string>();
  const [sending, setSending] = useState(false);
  const [sendProblem, setSendProblem] = useState<Problem>();
  const [pause, setPause] = useState<SmsPause | null | undefined>(me?.sms_pause);
  const fallback = me ? fallbackOf({ ...me, sms_pause: pause ?? null }) : 'none';
  const codeWords = fallback === 'code' ? 'the code from your authenticator app' : 'a code by text message';

  useEffect(() => setPause(me?.sms_pause), [me]);

  useEffect(() => {
    let live = true;
    if (!me) return;
    void (async () => {
      const [support, key] = await Promise.all([biometricSupport(), localApprovalKey(me.id)]);
      if (!live) return;
      setLabel(support.label);
      if (support.available && key) {
        setMode('biometric');
        return;
      }
      setMode(fallback);
      if (key && !support.available) setNote(`${support.reason ?? `${support.label} is not available.`} Use ${codeWords}.`);
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  const toCode = useCallback(
    (why?: string) => {
      setMode(fallback);
      setNote(why);
    },
    [fallback],
  );

  const send = useCallback(async () => {
    setSending(true);
    setSendProblem(undefined);
    try {
      const r = await api.post<{ sent_to: string }>('/v1/auth/mfa/sms');
      setSentTo(r.sent_to);
      setCode('');
    } catch (e) {
      const p = toProblem(e) as Problem & { reason?: SmsPause['reason']; paused_until?: string };
      if (p.code === 'sms-paused') {
        setPause({ reason: p.reason ?? 'phone_changed', until: p.paused_until ?? '', detail: p.detail });
        setMode((m) => (m === 'biometric' ? m : 'paused'));
        void reloadMe();
      } else setSendProblem(p);
    } finally {
      setSending(false);
    }
  }, [api, reloadMe]);

  const confirm = useCallback(
    async (opts: { stepUp?: boolean } = {}): Promise<ConfirmResult> => {
      if (!me) return { ok: false };
      if (mode === 'biometric') {
        const r = await biometricStepUp(api, me.id, label);
        if (r.ok) {
          setCancels(0);
          return { ok: true, code: '', method: 'device_biometric' };
        }
        if (r.reason === 'cancelled') {
          const n = cancels + 1;
          setCancels(n);
          if (n >= MAX_BIOMETRIC_CANCELS) {
            toCode(`${label} was cancelled ${MAX_BIOMETRIC_CANCELS} times. Use ${codeWords}.`);
            return { ok: false, cancelled: true };
          }
          return {
            ok: false,
            cancelled: true,
            problem: { type: 'about:blank', title: `${label} cancelled`, status: 0, code: 'biometric-cancelled', detail: `Nothing was approved. Hold again, or use the code instead.` },
          };
        }
        if (r.reason === 'unavailable' || r.reason === 'revoked') {
          toCode(r.problem?.detail ?? `${label} is not available. Use ${codeWords}.`);
          return { ok: false };
        }
        return { ok: false, problem: r.problem };
      }
      if (code.length < 6 || (mode !== 'code' && mode !== 'sms')) return { ok: false };
      if (mode === 'sms') {
        // An SMS code always goes to the step-up, where every wrong try counts (FR-ACC-015).
        try {
          await api.post('/v1/auth/mfa/step-up', { method: 'sms', code });
          return { ok: true, code: '', method: 'sms_code' };
        } catch (e) {
          setCode('');
          const p = toProblem(e);
          if (p.code === 'sms-paused') void reloadMe();
          return { ok: false, problem: p };
        }
      }
      if (opts.stepUp) {
        try {
          await api.post('/v1/auth/mfa/step-up', { code });
        } catch (e) {
          setCode('');
          return { ok: false, problem: toProblem(e) };
        }
      }
      return { ok: true, code, method: 'totp' };
    },
    [api, me, mode, label, cancels, code, toCode, codeWords, reloadMe],
  );

  return {
    mode,
    fallback,
    label,
    note,
    code,
    setCode,
    sentTo,
    sending,
    send,
    sendProblem,
    pause,
    phone: me?.phone_masked,
    ready: mode === 'biometric' || ((mode === 'code' || mode === 'sms') && code.length === 6),
    confirm,
    switchToCode: () => toCode(),
    reset: () => setCode(''),
  };
}

/**
 * What the person sees above the hold button: with Face ID, one line saying
 * the phone asks after the hold and a way to use the code instead; with the
 * authenticator, the six boxes; with SMS, "Send me a code" then the six boxes;
 * while SMS approvals are paused, why and until when. Nothing when the person
 * has no second factor yet.
 */
export function SecondFactorInput({ factor }: { factor: SecondFactor }) {
  const p = usePalette();
  if (factor.mode === 'loading' || factor.mode === 'none') return null;
  if (factor.mode === 'biometric') {
    const other = factor.fallback === 'sms' ? 'Use a code by text message instead' : factor.fallback === 'code' ? 'Use the code instead' : null;
    return (
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
        <View style={{ width: 44, height: 44, borderRadius: 14, borderWidth: 2, borderColor: brand.orange, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={factor.label === 'Face ID' || factor.label === 'face unlock' ? 'scan-outline' : 'finger-print'} size={24} color={brand.orange} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <T v="callout">{`Hold the button, then confirm with ${factor.label}.`}</T>
          {other ? (
            <Pressable onPress={factor.switchToCode} accessibilityRole="button" accessibilityLabel={other} hitSlop={8} style={{ minHeight: 44, justifyContent: 'center' }}>
              <T v="footnote" style={{ textDecorationLine: 'underline', color: p.textMuted }}>{other}</T>
            </Pressable>
          ) : null}
        </View>
      </View>
    );
  }
  if (factor.mode === 'paused') return <SmsPaused pause={factor.pause} />;
  if (factor.mode === 'sms') {
    return (
      <View style={{ gap: space[3] }}>
        {factor.note ? <T v="footnote" muted>{factor.note}</T> : null}
        {factor.sentTo ? (
          <>
            <T v="callout">{`We sent a code to ${factor.sentTo}. It works for 5 minutes.`}</T>
            <CodeField label="Code from the text message" value={factor.code} onChange={factor.setCode} />
            <Button title="Send a new code" variant="quiet" icon="refresh" loading={factor.sending} onPress={() => void factor.send()} />
            <T v="footnote" muted>Do not share this code. Tenmina will never call you for it.</T>
          </>
        ) : (
          <>
            <T v="callout">{`We text a 6-digit code to ${factor.phone || 'your phone'}. Enter it, then hold to approve.`}</T>
            <Button title="Send me a code" variant="dark" icon="chatbubble-ellipses-outline" loading={factor.sending} onPress={() => void factor.send()} />
          </>
        )}
        {factor.sendProblem ? (
          <View accessibilityRole="alert" style={{ borderRadius: radius.lg, borderWidth: 2, borderColor: p.text, padding: space[3] }}>
            <T v="callout">{factor.sendProblem.detail}</T>
          </View>
        ) : null}
      </View>
    );
  }
  return (
    <View style={{ gap: space[2] }}>
      {factor.note ? <T v="footnote" muted>{factor.note}</T> : null}
      <CodeField label="Code from your authenticator app" value={factor.code} onChange={factor.setCode} />
    </View>
  );
}

/** Why approvals by text message are paused and until when (FR-ACC-015). Orange: it needs this person. */
export function SmsPaused({ pause }: { pause?: SmsPause | null }) {
  return (
    <View accessibilityRole="alert" style={{ borderRadius: radius.lg, borderWidth: 2, borderColor: brand.orange, padding: space[4], gap: space[2] }}>
      <Label color={brand.orange}>Approvals by text message are paused</Label>
      <T v="callout">{pause?.detail ?? 'Approvals by text message are paused for 72 hours after your number changes.'}</T>
    </View>
  );
}
