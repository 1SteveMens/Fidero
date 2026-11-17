import { ed25519 } from '@noble/curves/ed25519.js';

/**
 * The approval key's arithmetic (FR-ACC-014): pure functions, shared with the
 * tests. The phone signs the server's one-time challenge with Ed25519; the
 * server checks it with the public key registered for this person and phone.
 * Pure JavaScript, so it runs in Expo Go.
 */

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function base64(b: Uint8Array): string {
  let out = '';
  for (let i = 0; i < b.length; i += 3) {
    const n = (b[i] << 16) | ((b[i + 1] ?? 0) << 8) | (b[i + 2] ?? 0);
    out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63] + (i + 1 < b.length ? B64[(n >> 6) & 63] : '=') + (i + 2 < b.length ? B64[n & 63] : '=');
  }
  return out;
}

export function base64url(b: Uint8Array): string {
  return base64(b).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function hex(b: Uint8Array): string {
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}

export function fromHex(h: string): Uint8Array {
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function utf8(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

/** What the phone signs: the same fixed prefix as the API (accounts.services.STEP_UP_PREFIX), then the challenge. */
export const STEP_UP_PREFIX = 'tenmina-step-up:v1:';

export function stepUpMessage(challenge: string): string {
  return STEP_UP_PREFIX + challenge;
}

/** The 32-byte public key, base64, as POST /v1/auth/approval-keys takes it. */
export function approvalPublicKey(secret: Uint8Array): string {
  return base64(ed25519.getPublicKey(secret));
}

/** The signature over the message the server sent with the challenge, base64url. */
export function signStepUpMessage(secret: Uint8Array, message: string): string {
  return base64url(ed25519.sign(utf8(message), secret));
}
