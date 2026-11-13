import { ed25519 } from '@noble/curves/ed25519.js';
import { sha256 } from '@noble/hashes/sha2.js';

/**
 * Canonical JSON and signatures for the signed evidence payload (02 section 8.4).
 * Pure functions, shared with the tests; the key itself is in signing.ts.
 */

/** RFC 8785 canonical JSON: keys sorted by UTF-16 code units, numbers in ECMAScript form, no spaces. */
export function canonical(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('NaN and infinity are not allowed in a manifest');
    return JSON.stringify(value);
  }
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== undefined);
    entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
  }
  throw new Error(`Cannot canonicalise ${typeof value}`);
}

export function utf8(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

export function hex(b: Uint8Array): string {
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}

export function fromHex(h: string): Uint8Array {
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(i * 2, i * 2 + 2), 16);
  return out;
}

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

export function sha256Hex(data: Uint8Array | string): string {
  return hex(sha256(typeof data === 'string' ? utf8(data) : data));
}

/** SubjectPublicKeyInfo DER for an Ed25519 key: a fixed 12-byte header, then the 32-byte key. */
export function spki(pub: Uint8Array): string {
  const head = fromHex('302a300506032b6570032100');
  const der = new Uint8Array(head.length + pub.length);
  der.set(head);
  der.set(pub, head.length);
  return base64(der);
}

export function publicKeyOf(secret: Uint8Array): string {
  return spki(ed25519.getPublicKey(secret));
}

export interface Signed<M> {
  manifest: M;
  signature: string;
  signature_alg: 'EdDSA';
}

/** Sign a manifest's canonical bytes with an Ed25519 secret key. */
export function signWith<M extends object>(secret: Uint8Array, manifest: M): Signed<M> {
  return { manifest, signature: base64url(ed25519.sign(utf8(canonical(manifest)), secret)), signature_alg: 'EdDSA' };
}
