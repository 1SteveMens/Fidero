# Tenmina Field

The app for field roles: inspectors, contractors, carers, and later runners, surveyors and errand agents (`docs/specs/01` module MOB). Same code base and Bloc design as the client app (`docs/specs/03` sections 2.3 and 6.1c), and the same `@tenmina/mobile` connection to the `/v1` API with the `Tenmina-App: field/<platform>/<version>` header. Set the API's address with `EXPO_PUBLIC_API_URL`.

## Run it

See `docs/operations/testing-the-apps.md`. Sign in with a seeded field user (`inspector@example.com`, `builder@example.com`, `carer@example.com`, `runner@example.com`, `kofi.agent@example.com`; password `tenmina-dev-123`).

## How it works

- **This phone's key** (02 8.2): after sign-in the app asks `/v1/mobile/devices/challenge`, makes an Ed25519 key, and registers it with `/v1/mobile/devices` and the platform attestation. This build uses a software key kept in the keychain or keystore (`expo-secure-store`) and sends the development server's fake attestation, marked as a stand-in.
- **Signed evidence** (02 8.4): every capture is fingerprinted (SHA-256) and, when kept, its manifest is signed as RFC 8785 canonical JSON, chained to the previous item from the phone. `test/canonical.test.ts` checks the bytes and the signature against the API's own `mobile/crypto.py`.
- **Offline first** (8.5, FR-MOB-005): jobs come from `/v1/mobile/sync` and stay on the phone. Everything the person does goes into an ordered queue saved to the phone's storage: evidence (register, upload, complete), submissions, inspections, signed check-ins and check-outs, care plan items, concerns, errand steps and expense claims. Each item carries its own client-generated id, so a retry never doubles. Photos are deleted from the phone once the server stores them.
- **Camera only** (RUL-08): no gallery or file picker. The web preview, a development tool, uses a file input only when `EXPO_PUBLIC_DEV_FILE_CAPTURE=1` or in development.

## Screens

| Route | Screen |
|---|---|
| `/welcome` | Sign in and register this phone (SCR-MOB-01) |
| `/` | My jobs (SCR-MOB-02), the next one in orange, errands for agents |
| `/job/[type]/[id]` | Milestone and task evidence (SCR-MOB-03, 04, 07, 12) with the RUL-30 strip on search tasks; inspection checklist, defects and result (SCR-MOB-09 to 11, 18) with the conflict strip; care visit check-in, plan items with readings, concern and check-out (SCR-MOB-14 to 16) |
| `/capture` | Camera and "Check this capture" (SCR-MOB-05, 06) |
| `/errand/[id]` | Errand steps, receipts, result and handover (SCR-MOB-17) |
| `/queue` | Upload queue (SCR-MOB-08) |
| `/pay`, `/pay/[id]`, `/pay/claim`, `/pay/statements` | My pay, payable detail, claim an expense, statements (SCR-MOB-19 to 22), in black, white and lime only |
| `/account`, `/delete` | Account and storage (SCR-MOB-13), delete my account (SCR-APP-04) |

## Not yet

- **Hardware keys and real attestation** (Secure Enclave or Android Keystore with App Attest or Play Integrity): needs native code and a test build, not Expo Go.
- **Encrypting stored evidence at rest** on the phone (FR-MOB-009) beyond the app's private storage.
- Property inspection (SCR-MOB-18) works through the inspection screen when the API assigns one; none is seeded.
