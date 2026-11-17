import { describe, expect, it } from 'vitest';
import { ed25519 } from '@noble/curves/ed25519.js';
import { approvalPublicKey, base64url, fromHex, hex, signStepUpMessage, stepUpMessage, utf8 } from '../src/approvalkey';

// The same seed and message signed by the API's library (Python `cryptography`): Ed25519 is
// deterministic, so the phone's signature must match byte for byte (FR-ACC-014).
const SEED = Uint8Array.from({ length: 32 }, (_, i) => i);
const PUBLIC = 'A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=';
const SIGNATURE = 'THjVN8-vqV1THksF0EGShvWwfY4X5--nAC85YVj_ljbjIykLr23QGa678wIyghST4h0tXzRzktpXvV0uc4BrBQ';

describe('approval key', () => {
  it('signs the step-up message exactly as the API checks it', () => {
    expect(stepUpMessage('abc123-_XYZ')).toBe('tenmina-step-up:v1:abc123-_XYZ');
    expect(approvalPublicKey(SEED)).toBe(PUBLIC);
    expect(signStepUpMessage(SEED, stepUpMessage('abc123-_XYZ'))).toBe(SIGNATURE);
  });

  it('a signature over another challenge does not verify', () => {
    const sig = signStepUpMessage(SEED, stepUpMessage('one'));
    const raw = Uint8Array.from(atob(sig.replace(/-/g, '+').replace(/_/g, '/') + '=='.slice(0, (4 - (sig.length % 4)) % 4)), (c) => c.charCodeAt(0));
    expect(base64url(raw)).toBe(sig);
    expect(ed25519.verify(raw, utf8(stepUpMessage('one')), ed25519.getPublicKey(SEED))).toBe(true);
    expect(ed25519.verify(raw, utf8(stepUpMessage('two')), ed25519.getPublicKey(SEED))).toBe(false);
  });

  it('keeps the secret round trip through hex', () => {
    expect(fromHex(hex(SEED))).toEqual(SEED);
  });
});
