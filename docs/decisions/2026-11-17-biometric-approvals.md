# Decision: Face ID or fingerprint for approvals in the phone apps

Date: 17 November 2026. Decided by the founder.

## What changed

In the two phone apps, Tenmina and Tenmina Field, a person approves a payment with Face ID or a fingerprint instead of typing the 6-digit code from the authenticator app every time. The ticket and the press-and-hold button stay. When the hold completes, the phone asks for Face ID or a fingerprint, and the approval goes.

The security model does not change. Every approval still needs a fresh second factor (within 5 minutes), bound to this person and this phone, and recorded on the approval. Requirement FR-ACC-014 in `docs/specs/01` holds the rule; 02 ADR-13 the design; 03 section 5.4 the screens; 05 the tests TC-ACC-014-01 to -09.

## How it works

1. **Turning it on, once per phone.** After sign-in the app offers "Use Face ID for approvals" ("fingerprint" on Android). The phone makes a new Ed25519 key pair. The private key stays on the phone, in the keychain or keystore. Tenmina receives only the public key, with the phone's name. Turning it on needs the authenticator code once (the code entered at sign-in counts for 5 minutes). So a stolen password alone can never add a phone.
2. **Each approval.** After the hold, the app asks Tenmina for a one-time challenge (random, 2 minutes, single use). The phone asks for Face ID or a fingerprint to read the private key, signs the challenge, and sends the signature. Tenmina checks it with the public key. A valid signature counts exactly as a code: the step-up lasts 5 minutes, and the approval records the method `device_biometric` instead of `totp`.
3. **Falling back.** The six code boxes show instead when the phone has no Face ID or fingerprint set up, the person has not turned it on, the key was removed, the person taps "Use the code instead", or Face ID is cancelled three times.
4. **Managing phones.** Account lists this phone and other phones, and removes any of them. A password reset, a locked account, a suspension or switching the authenticator off removes every phone at once.
5. **Audit.** Turning a phone on, removing it, and every Face ID step-up (and every refusal) go into the hash-chained audit log. The person is told on two channels when a phone is added.

## What Tenmina never holds

No face, fingerprint or other biometric data reaches Tenmina. The phone checks the face or finger itself and only then releases the key. Tenmina keeps a public key and a hash of it. This keeps ADR-25 (no biometric data in any table).

## Why this is still two factors

Signing in needs the password (something the person knows). An approval then needs the private key that exists only on this phone (something they have), released by their face or finger (something they are). Unlocking the app with Face ID alone still never counts as a second factor. The authenticator stays as the back-up and as the way to add a phone.

## Limits, now and later

- **Expo Go.** The founder tests in Expo Go. Expo Go cannot ask the keychain itself to demand Face ID before giving out a key. There, the app asks for Face ID first and then reads the key; the key is still kept only on this device and never backed up. Store builds use the keychain's own Face ID lock (`requireAuthentication`), so a new face or finger added to the phone invalidates the key and the person turns it on again with one code. In Expo Go, Face ID shows Expo Go's own permission text, not Tenmina's.
- **Web.** The portal and back office keep the authenticator code. The later web equivalent is WebAuthn passkeys.
- **Field app.** Tenmina Field has no approval screens today. It carries the Face ID permission text so the same key flow can be used when a field approval is added.
- **Software key.** The key is an Ed25519 key in the keychain or keystore, not a key made inside the Secure Enclave. A later native build can move it into the Secure Enclave or StrongBox with ECDSA P-256; the API already checks both kinds of signature for field devices.

## What does not change

- The client approves first; two different Tenmina staff with release rights approve next; silence is never approval (RUL-05, RUL-11).
- The 5-minute freshness of every step-up, in the service and in the database trigger on `core_approval`.
- Tenmina never holds client money; money goes only to verified payees.

## Figures

The 2-minute challenge life, the limit of 5 phones per person and the 3 cancelled prompts before the code boxes show are working assumptions, not verified data.
