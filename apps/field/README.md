# Tenmina Field

The app for field roles: inspectors, contractors, carers, and later runners, surveyors and errand agents (`docs/specs/01` module MOB). Same code base and Bloc design as the client app (`docs/specs/03` sections 2.3 and 6.1c). Runs on sample data from `@tenmina/shared` (`createSampleFieldApi`).

## Run it

See `docs/operations/testing-the-apps.md`. In short, from the repository root:

```bash
pnpm install
```

```bash
cd apps/field && npx expo start
```

Scan the QR code with the phone's camera to open it in Expo Go. On the sign-in screen, pick the role to try: Inspector, Contractor or Carer.

## What works

| Screen | Requirement |
|---|---|
| Sign in, with a demo role picker (SCR-MOB-01) | FR-MOB-001 |
| My jobs for the day, the next job in orange, the queue count | FR-MOB-001 |
| Inspection checklist: big Yes and No, a photo per check, defects with a value, Pass / Pass with defects / Fail, submit blocked until complete | FR-MOB-007, RUL-09, RUL-10 |
| Contractor milestone: the evidence list, submit blocked until every item has its captures | FR-MOB-006 |
| Camera only, no gallery or file picker anywhere; photos and videos capped at 30 seconds | FR-MOB-002, FR-MOB-008, RUL-08 |
| "Check this photo": distance from the site with a "say why" when it is far, the time, and the SHA-256 fingerprint | FR-MOB-003, FR-MOB-004 (fingerprint part) |
| Care visit: distance to the address, check in, the plan with photo items, raise a concern, check out with a reason for items left | FR-MOB-012, FR-CARE-003, FR-CARE-006, RUL-23 |
| Upload queue saved to the phone's storage, kept through a restart, sent when online | FR-MOB-005 |
| My pay for professionals, with no verdict colour | FR-PRO-002, FR-PRO-008, RUL-26, RUL-27 |
| Account: evidence count, waiting items, and a demo switch "Pretend there is no signal" | |

## Not yet

- **Signing in the phone's secure chip** (Secure Enclave or Android Keystore, with App Attest or Play Integrity) for FR-MOB-004. Each capture is fingerprinted now; the signature needs native code and a test build, not Expo Go.
- **Encrypting stored evidence** (FR-MOB-009) and deleting it after the server confirms receipt.
- **A real server.** The queue marks items received a moment after the phone is online.
- Runners, surveyors and errand agents (FR-MOB-010), property inspections (SCR-MOB-18), expense claims and statements in My pay (SCR-MOB-21, SCR-MOB-22).
