import { useCallback, useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { CodeField, T, usePalette } from '@tenmina/ui';
import { toProblem, type Problem } from './api';
import { biometricStepUp, biometricSupport, localApprovalKey, type BiometricLabel } from './biometric';
import { useSession } from './session';

/** After this many cancelled Face ID prompts the approval falls back to the code boxes (FR-ACC-014). */
export const MAX_BIOMETRIC_CANCELS = 3;

export type FactorMode = 'loading' | 'biometric' | 'code' | 'none';

export type ConfirmResult =
  /** `code` is the authenticator code to send with the action; empty when Face ID already stepped up. */
  | { ok: true; code: string; method: 'device_biometric' | 'totp' }
  | { ok: false; problem?: Problem; cancelled?: boolean };

export interface SecondFactor {
  /** "biometric": Face ID or fingerprint after the hold. "code": the six boxes. "none": no authenticator yet. */
  mode: FactorMode;
  label: BiometricLabel;
  /** Why the code boxes show although this phone had Face ID turned on. */
  note?: string;
  code: string;
  setCode: (v: string) => void;
  /** True when the hold button may start: Face ID is ready, or six digits are in. */
  ready: boolean;
  /** Run the second factor. With `stepUp` the code is sent to /v1/auth/mfa/step-up here too. */
  confirm: (opts?: { stepUp?: boolean }) => Promise<ConfirmResult>;
  /** Show the code boxes instead of Face ID. */
  switchToCode: () => void;
  /** Clear the code after a failed try. */
  reset: () => void;
}

/**
 * The second factor for one approval (FR-ACC-003, FR-ACC-014): Face ID or a
 * fingerprint where this phone has an approval key, else the 6-digit code.
 * Three cancelled prompts, a revoked key or no biometric on the phone fall
 * back to the code. A browser always uses the code.
 */
export function useSecondFactor(): SecondFactor {
  const { api, me } = useSession();
  const [mode, setMode] = useState<FactorMode>('loading');
  const [label, setLabel] = useState<BiometricLabel>('Face ID');
  const [note, setNote] = useState<string>();
  const [code, setCode] = useState('');
  const [cancels, setCancels] = useState(0);

  useEffect(() => {
    let live = true;
    if (!me) return;
    if (!me.mfa_enabled) {
      setMode('none');
      return;
    }
    void (async () => {
      const [support, key] = await Promise.all([biometricSupport(), localApprovalKey(me.id)]);
      if (!live) return;
      setLabel(support.label);
      setMode(support.available && key ? 'biometric' : 'code');
      if (key && !support.available) setNote(`${support.reason ?? `${support.label} is not available.`} Use the code from your authenticator app.`);
    })();
    return () => {
      live = false;
    };
  }, [me]);

  const toCode = useCallback((why?: string) => {
    setMode('code');
    setNote(why);
  }, []);

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
            toCode(`${label} was cancelled ${MAX_BIOMETRIC_CANCELS} times. Use the code from your authenticator app.`);
            return { ok: false, cancelled: true };
          }
          return {
            ok: false,
            cancelled: true,
            problem: { type: 'about:blank', title: `${label} cancelled`, status: 0, code: 'biometric-cancelled', detail: `Nothing was approved. Hold again, or use the code instead.` },
          };
        }
        if (r.reason === 'unavailable' || r.reason === 'revoked') {
          toCode(r.problem?.detail ?? `${label} is not available. Use the code from your authenticator app.`);
          return { ok: false };
        }
        return { ok: false, problem: r.problem };
      }
      if (code.length < 6) return { ok: false };
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
    [api, me, mode, label, cancels, code, toCode],
  );

  return {
    mode,
    label,
    note,
    code,
    setCode,
    ready: mode === 'biometric' || (mode === 'code' && code.length === 6),
    confirm,
    switchToCode: () => toCode(),
    reset: () => setCode(''),
  };
}

/**
 * What the person sees above the hold button: with Face ID, one line saying
 * the phone asks after the hold and a way to use the code instead; otherwise
 * the six code boxes. Nothing when the person has no authenticator yet.
 */
export function SecondFactorInput({ factor }: { factor: SecondFactor }) {
  const p = usePalette();
  if (factor.mode === 'loading' || factor.mode === 'none') return null;
  if (factor.mode === 'biometric') {
    return (
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
        <View style={{ width: 44, height: 44, borderRadius: 14, borderWidth: 2, borderColor: brand.orange, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={factor.label === 'Face ID' || factor.label === 'face unlock' ? 'scan-outline' : 'finger-print'} size={24} color={brand.orange} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <T v="callout">{`Hold the button, then confirm with ${factor.label}.`}</T>
          <Pressable onPress={factor.switchToCode} accessibilityRole="button" accessibilityLabel="Use the code from your authenticator app instead" hitSlop={8} style={{ minHeight: 44, justifyContent: 'center' }}>
            <T v="footnote" style={{ textDecorationLine: 'underline', color: p.textMuted }}>Use the code instead</T>
          </Pressable>
        </View>
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
