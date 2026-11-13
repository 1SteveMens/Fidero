import * as Crypto from 'expo-crypto';
import { secureDelete, secureGet, secureSet } from '@tenmina/mobile';
import { fromHex, hex, publicKeyOf, signWith, type Signed } from './canonical';

export * from './canonical';

/**
 * This phone's signing key (02 section 8.2). In the store build the key lives
 * in the Secure Enclave or Android Keystore and is attested by App Attest or
 * Play Integrity. This build uses a software Ed25519 key kept in the keychain
 * or keystore through expo-secure-store; the development server's attestation
 * is a fake, so evidence from this build proves the flow, not the hardware.
 */

const KEY = 'tenmina.field.signing_key';

export interface SigningKey {
  secret: Uint8Array;
  publicKey: string;
  alg: 'EdDSA';
  security: 'software';
}

/** This install's key, made once. Signing out forgets it, so the next person registers a new one. */
export async function signingKey(create = true): Promise<SigningKey | null> {
  let h = await secureGet(KEY);
  if (!h && !create) return null;
  if (!h) {
    h = hex(Crypto.getRandomBytes(32));
    await secureSet(KEY, h);
  }
  const secret = fromHex(h);
  return { secret, publicKey: publicKeyOf(secret), alg: 'EdDSA', security: 'software' };
}

export async function forgetSigningKey(): Promise<void> {
  await secureDelete(KEY);
}

/** Sign a manifest: its canonical bytes, with this phone's key. */
export function sign<M extends object>(key: SigningKey, manifest: M): Signed<M> {
  return signWith(key.secret, manifest);
}
