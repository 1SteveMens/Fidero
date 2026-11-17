import { Platform } from 'react-native';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as Crypto from 'expo-crypto';
import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';
import { ApiError, toProblem, type MobileApi, type Problem } from './api';
import { approvalPublicKey, fromHex, hex, signStepUpMessage } from './approvalkey';
import { secureDelete, secureGet, secureSet } from './storage';

/**
 * Face ID or fingerprint for approvals (FR-ACC-014, ADR-13).
 *
 * Enrolment makes an Ed25519 key on this phone and registers only its public
 * half, once, with the authenticator code. At each approval the server sends a
 * one-time challenge, the phone asks for Face ID or a fingerprint to read the
 * private key, signs the challenge and steps up. The face or fingerprint never
 * leaves the phone and Tenmina never sees it.
 *
 * Where the platform supports it (store builds), the key is kept with
 * `requireAuthentication`, so the keychain or keystore itself refuses to give
 * it out without the biometric. Expo Go cannot use that option, so there the
 * key is kept as this phone's other secrets are and the app asks for the
 * biometric with expo-local-authentication before reading it.
 */

export type BiometricLabel = 'Face ID' | 'Touch ID' | 'fingerprint' | 'face unlock';

export interface BiometricSupport {
  available: boolean;
  label: BiometricLabel;
  /** Why not, in plain words, when it is not available. */
  reason?: string;
}

interface Stored {
  keyId: string;
  /** "store": the keychain or keystore asks for the biometric. "app": the app asks first (Expo Go). */
  gate: 'store' | 'app';
  deviceName: string;
}

const safe = (personId: string) => personId.replace(/[^A-Za-z0-9._-]/g, '');
const secretName = (personId: string) => `tenmina.approval.secret.${safe(personId)}`;
const metaName = (personId: string) => `tenmina.approval.meta.${safe(personId)}`;
const offeredName = (personId: string) => `tenmina.approval.offered.${safe(personId)}`;

/** Expo Go (or a development client): the keychain's own biometric gate is not available there. */
function inExpoGo(): boolean {
  return Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
}

function storeGateAvailable(): boolean {
  if (inExpoGo()) return false;
  try {
    return SecureStore.canUseBiometricAuthentication();
  } catch {
    return false;
  }
}

/** Is Face ID or a fingerprint set up on this phone? Never in a browser. */
export async function biometricSupport(): Promise<BiometricSupport> {
  const fallback: BiometricLabel = Platform.OS === 'ios' ? 'Face ID' : 'fingerprint';
  if (Platform.OS === 'web') return { available: false, label: fallback, reason: 'A browser has no Face ID or fingerprint for Tenmina.' };
  try {
    const [hardware, enrolled, types] = await Promise.all([
      LocalAuthentication.hasHardwareAsync(),
      LocalAuthentication.isEnrolledAsync(),
      LocalAuthentication.supportedAuthenticationTypesAsync(),
    ]);
    const face = types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION);
    const finger = types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT);
    const label: BiometricLabel = Platform.OS === 'ios' ? (face ? 'Face ID' : 'Touch ID') : finger ? 'fingerprint' : face ? 'face unlock' : 'fingerprint';
    if (!hardware) return { available: false, label, reason: 'This phone has no Face ID or fingerprint reader.' };
    if (!enrolled) return { available: false, label, reason: `Set up ${label} in the phone's settings first.` };
    // Android: only a strong (class 3) biometric may release an approval key.
    if (Platform.OS === 'android' && (await LocalAuthentication.getEnrolledLevelAsync()) < LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG) {
      return { available: false, label, reason: "This phone's fingerprint or face unlock is not strong enough for approvals." };
    }
    return { available: true, label };
  } catch {
    return { available: false, label: fallback, reason: 'This phone did not say whether it has Face ID or a fingerprint reader.' };
  }
}

/** The approval key this phone holds for the person, if any. */
export async function localApprovalKey(personId: string): Promise<Stored | null> {
  const raw = await secureGet(metaName(personId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Stored;
  } catch {
    return null;
  }
}

/** Forget this phone's key (after a revocation, or when the person turns it off). */
export async function forgetApprovalKey(personId: string): Promise<void> {
  await secureDelete(metaName(personId));
  if (Platform.OS === 'web') return;
  try {
    await SecureStore.deleteItemAsync(secretName(personId));
  } catch {
    // already gone
  }
}

/** Has the app already offered Face ID for approvals to this person on this phone? It offers once. */
export async function biometricOffered(personId: string): Promise<boolean> {
  return (await secureGet(offeredName(personId))) !== null;
}

export async function markBiometricOffered(personId: string, answer: 'on' | 'not_now'): Promise<void> {
  await secureSet(offeredName(personId), answer);
}

export function deviceName(): string {
  const name = Constants.deviceName?.trim();
  if (name) return name.slice(0, 80);
  return Platform.OS === 'ios' ? 'iPhone' : 'Android phone';
}

export type EnrolResult = { ok: true; keyId: string } | { ok: false; needsCode?: boolean; cancelled?: boolean; problem?: Problem };

function cancelled(error: string): boolean {
  return ['user_cancel', 'system_cancel', 'app_cancel', 'user_fallback', 'authentication_failed', 'timeout'].includes(error);
}

/**
 * Turn on Face ID or fingerprint for approvals on this phone (FR-ACC-014).
 * Without `code` it relies on the code entered at sign-in, if that was in the
 * last 5 minutes; the API answers `needsCode` otherwise.
 */
export async function enrolApprovalKey(api: MobileApi, personId: string, label: BiometricLabel, code?: string): Promise<EnrolResult> {
  const support = await biometricSupport();
  if (!support.available) return { ok: false, problem: plain('Not available', support.reason ?? 'Face ID or fingerprint is not available.') };
  const gate: Stored['gate'] = storeGateAvailable() ? 'store' : 'app';
  const secret = Crypto.getRandomBytes(32);
  const prompt = `Turn on ${label} for Tenmina approvals`;
  try {
    if (gate === 'app') {
      const r = await LocalAuthentication.authenticateAsync({ promptMessage: prompt, cancelLabel: 'Not now', disableDeviceFallback: true, biometricsSecurityLevel: 'strong' });
      if (!r.success) return { ok: false, cancelled: cancelled(r.error), problem: cancelled(r.error) ? undefined : plain('Not turned on', `${label} did not work: ${r.error.replace(/_/g, ' ')}.`) };
    }
    // Store the key first, so a key the phone could not keep is never registered.
    try {
      await SecureStore.setItemAsync(secretName(personId), hex(secret), gate === 'store'
        ? { requireAuthentication: true, authenticationPrompt: prompt, keychainAccessible: SecureStore.WHEN_PASSCODE_SET_THIS_DEVICE_ONLY }
        : { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY });
    } catch (e) {
      return { ok: false, cancelled: true, problem: plain('Not turned on', `This phone could not keep the key: ${String((e as Error)?.message ?? e)}`) };
    }
    const name = deviceName();
    let keyId: string;
    try {
      const out = await api.post<{ id: string }>('/v1/auth/approval-keys', {
        public_key: approvalPublicKey(secret),
        device_name: name,
        platform: Platform.OS === 'android' ? 'android' : 'ios',
        ...(code ? { code } : {}),
      });
      keyId = out.id;
    } catch (e) {
      await SecureStore.deleteItemAsync(secretName(personId)).catch(() => undefined);
      const problem = toProblem(e);
      return { ok: false, needsCode: problem.code === 'mfa-required' || problem.code === 'mfa-invalid', problem: problem.code === 'mfa-required' ? undefined : problem };
    }
    await secureSet(metaName(personId), JSON.stringify({ keyId, gate, deviceName: name } satisfies Stored));
    await markBiometricOffered(personId, 'on');
    return { ok: true, keyId };
  } finally {
    secret.fill(0);
  }
}

export type BiometricStepUp =
  | { ok: true }
  | { ok: false; reason: 'cancelled' | 'unavailable' | 'revoked' | 'error'; problem?: Problem };

/**
 * A fresh MFA step-up with Face ID or a fingerprint: get a one-time challenge,
 * read the key behind the biometric, sign, and send it to
 * POST /v1/auth/mfa/step-up. The approval itself is sent after this.
 */
export async function biometricStepUp(api: MobileApi, personId: string, label: BiometricLabel, prompt = `Approve with ${label}`): Promise<BiometricStepUp> {
  const stored = await localApprovalKey(personId);
  if (!stored || Platform.OS === 'web') return { ok: false, reason: 'unavailable' };
  let challenge: { challenge: string; message: string };
  try {
    challenge = await api.post<{ challenge: string; message: string }>('/v1/auth/mfa/challenge');
  } catch (e) {
    return { ok: false, reason: 'error', problem: toProblem(e) };
  }
  let hexSecret: string | null = null;
  if (stored.gate === 'store') {
    try {
      hexSecret = await SecureStore.getItemAsync(secretName(personId), { requireAuthentication: true, authenticationPrompt: prompt });
    } catch {
      return { ok: false, reason: 'cancelled' };
    }
  } else {
    const r = await LocalAuthentication.authenticateAsync({ promptMessage: prompt, cancelLabel: 'Use the code', disableDeviceFallback: true, biometricsSecurityLevel: 'strong' });
    if (!r.success) {
      if (cancelled(r.error)) return { ok: false, reason: 'cancelled' };
      return { ok: false, reason: 'unavailable', problem: plain(`${label} is not available`, `${label} did not work (${r.error.replace(/_/g, ' ')}). Use the code from your authenticator app.`) };
    }
    hexSecret = await SecureStore.getItemAsync(secretName(personId)).catch(() => null);
  }
  if (!hexSecret) {
    // The phone dropped the key (for example after a new face or finger was added).
    await forgetApprovalKey(personId);
    return { ok: false, reason: 'revoked', problem: plain(`${label} needs setting up again`, `This phone no longer holds the key. Use the code now, then turn on ${label} again in Account.`) };
  }
  const secret = fromHex(hexSecret);
  hexSecret = null;
  let signature: string;
  try {
    signature = signStepUpMessage(secret, challenge.message);
  } finally {
    secret.fill(0);
  }
  try {
    await api.post('/v1/auth/mfa/step-up', { key_id: stored.keyId, challenge: challenge.challenge, signature });
    return { ok: true };
  } catch (e) {
    const problem = toProblem(e);
    if (e instanceof ApiError && ['approval-key-revoked', 'approval-key-unknown'].includes(problem.code)) {
      await forgetApprovalKey(personId);
      return { ok: false, reason: 'revoked', problem };
    }
    return { ok: false, reason: 'error', problem };
  }
}

function plain(title: string, detail: string): Problem {
  return { type: 'about:blank', title, status: 0, detail, code: 'biometric' } as Problem;
}
