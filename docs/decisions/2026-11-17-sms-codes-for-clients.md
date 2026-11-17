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

## How it is built (17 November 2026)

Requirement FR-ACC-015 in `docs/specs/01` holds the rules; 02 ADR-13 the design; 03 section 5.4 and SCR-PTL-03 the screens; 05 the tests TC-ACC-015-01 to -10 and TC-SEC-55.

- **Who.** Clients and the client side: role CL (a representative holds CL), family members (FM) and tenants (TN), with a confirmed mobile number and no authenticator app. Never staff (CM, RV, AD, AN, DPO, SUP), professionals, field roles, or anyone holding release or payment rights (RR, PY). They are refused with a clear message, in the service, in the approval kernel and in the database.
- **Sign-in.** After the right password, the API sends a code and answers that a code is needed, with the masked number ("+44 •••• 123"). The client enters it. Posting again without a code sends a new one. A client whose second factor is SMS cannot sign in with a one-time code sent to that same phone instead of the password: the password stays the first factor.
- **Approvals.** "Send code", the six boxes, then press and hold. The code is checked only at the step-up, so every wrong try counts; the approval records `sms_code`.
- **Codes.** 6 digits, 5 minutes, used once, 5 tries then a new code, only a hash stored, every send and refusal audited. At most 3 codes in 10 minutes and 10 a day `[TO VERIFY]`. The text has no amount and no account number and says "Do not share this code. Tenmina will never call you for it."
- **Pause.** SMS approvals (and turning on Face ID with an SMS code) pause for 72 hours after the number changes, or after the mobile network's SIM-swap check reports a swap (a fake adapter for now, provider `[TO VERIFY]`). The client sees why and until when. Face ID on a phone where it is on, or the authenticator, still work. Signing in by SMS still works, so the client can see what is waiting.
- **New number.** Needs the password and the code sent to the new number. It removes every Face ID phone and tells the client by email.
- **Forgotten password.** For a client whose second factor is SMS, the reset needs the code from the email and the code from the text message. A stolen SIM alone never takes over the account.
- **Sending.** Through the notifications SMS provider port. In development the fake adapter writes the text, with the code, to the API log; the delivery log keeps it with the code hidden. Hubtel and Arkesel adapters are placeholders until a contract exists `[TO VERIFY]`.
- **Face ID phones are no longer removed when an account is locked** (`2026-11-17-biometric-approvals.md`, amended): anyone who knows the email address could lock the account on purpose.
