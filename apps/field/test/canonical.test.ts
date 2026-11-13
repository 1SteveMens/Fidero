import { describe, expect, it } from 'vitest';
import { base64, canonical, publicKeyOf, sha256Hex, signWith } from '../src/canonical';

// Vectors produced by the API's own mobile/crypto.py (canonical, sign, spki_b64)
// for the same manifest and the secret key bytes 0..31, so the phone and the
// server agree byte for byte (02 section 8.4).
const manifest = {
  schema: 'tenmina.evidence.v1',
  client_item_id: 'c1',
  device_id: '01a1d4c2-0000-7000-8000-000000000001',
  subject: { type: 'milestone', id: '01a1d4c2-0000-7000-8000-000000000002', requirement_key: 'rebar_photo' },
  captured_at_device: '2026-11-13T09:30:00.000Z',
  location: { lat: 5.6037, lng: -0.187, accuracy_m: 4.5, provider: 'gps', mock: false },
  media: { type: 'image/jpeg', size_bytes: 123456, sha256: 'ab'.repeat(32) },
  camera: { lens: 'back', model: 'iPhone15,2', platform: 'ios', app_version: '1.0.0' },
  last_server_time_sync: { server: '2026-11-13T09:00:00Z', offset_ms: -1200 },
  note: 'Ɛ café é "q" \n',
  elapsed_realtime_ms: 88123456,
  z: [1, 2.5, 1e-7, 1e21, 100.0],
};

const expected = JSON.parse(
  '"{\\"camera\\":{\\"app_version\\":\\"1.0.0\\",\\"lens\\":\\"back\\",\\"model\\":\\"iPhone15,2\\",\\"platform\\":\\"ios\\"},\\"captured_at_device\\":\\"2026-11-13T09:30:00.000Z\\",\\"client_item_id\\":\\"c1\\",\\"device_id\\":\\"01a1d4c2-0000-7000-8000-000000000001\\",\\"elapsed_realtime_ms\\":88123456,\\"last_server_time_sync\\":{\\"offset_ms\\":-1200,\\"server\\":\\"2026-11-13T09:00:00Z\\"},\\"location\\":{\\"accuracy_m\\":4.5,\\"lat\\":5.6037,\\"lng\\":-0.187,\\"mock\\":false,\\"provider\\":\\"gps\\"},\\"media\\":{\\"sha256\\":\\"abababababababababababababababababababababababababababababababab\\",\\"size_bytes\\":123456,\\"type\\":\\"image/jpeg\\"},\\"note\\":\\"\\u0190 caf\\u00e9 \\u00e9 \\\\\\"q\\\\\\" \\\\n\\",\\"schema\\":\\"tenmina.evidence.v1\\",\\"subject\\":{\\"id\\":\\"01a1d4c2-0000-7000-8000-000000000002\\",\\"requirement_key\\":\\"rebar_photo\\",\\"type\\":\\"milestone\\"},\\"z\\":[1,2.5,1e-7,1e+21,100]}"',
);

const secret = Uint8Array.from({ length: 32 }, (_, i) => i);

describe('signed evidence payload (02 8.4)', () => {
  it('serialises canonical JSON exactly as the server does', () => {
    expect(canonical(manifest)).toBe(expected);
  });

  it('drops undefined fields, as the server never sees them', () => {
    expect(canonical({ b: 1, a: undefined, c: [true, null] })).toBe('{"b":1,"c":[true,null]}');
  });

  it('signs with Ed25519 to the same bytes the server verifies', () => {
    const s = signWith(secret, manifest);
    expect(s.signature_alg).toBe('EdDSA');
    expect(s.signature).toBe('voGITSXwZtz4Bzzq3uN7xqXKVJNe18lMLDyjfjsxavTFqF0r2ue_LZQ1pJrJtKgfQ2TetykwwDz7q-MmTjJZDw');
  });

  it('gives the public key as SubjectPublicKeyInfo, base64', () => {
    expect(publicKeyOf(secret)).toBe('MCowBQYDK2VwAyEAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=');
  });

  it('fingerprints media with SHA-256 in hex', () => {
    expect(sha256Hex('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(base64(new Uint8Array([1, 2, 3, 4]))).toBe('AQIDBA==');
  });
});
