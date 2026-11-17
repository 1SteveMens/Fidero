# Decision: SMS codes for clients, authenticator app for staff

Date: 17 November 2026
Decided by: the founder

## Decision

1. **Clients sign in with a one-time code sent by SMS** instead of an authenticator app. The authenticator app stays available to any client who prefers it.
2. **Clients approve payments in the phone apps with Face ID or fingerprint** (decision of the same date, `2026-11-17-biometric-approvals.md`).
3. **On the website, or where biometrics are not available, clients approve payments with an SMS code**, with two safeguards:
   - SMS approvals pause for 72 hours after the client's phone number changes, or when the mobile network reports a recent SIM swap where that check is available `[TO VERIFY]`;
   - a change to the account a payment goes to keeps its 72-hour cooling-off (RUL-28), so a stolen number alone cannot redirect money.
4. **Staff keep the authenticator app** (or a passkey on their computer). Two staff approve every release for every client, so a SIM swap on one reviewer's phone must never be enough.

## Why

People abroad and their families find an SMS code easier than installing an authenticator app. SMS codes are weaker: a criminal who has a number moved to their own SIM receives the codes, and SIM-swap fraud is common in Ghana and Nigeria. So SMS is used where it is convenient and something stronger wherever money moves.

## Consequences

- An SMS provider in each country (in Ghana, for example Hubtel or Arkesel `[TO VERIFY]`); cost per message `[TO VERIFY]`. Until it is set up, codes are written to the API's log.
- Specs: ADR-13 and the MFA requirements in documents 01 and 02, the sign-in and approval screens in document 03, tests in document 05.
- Code: sign-in and approval step-up in the API, the portal and both apps.
