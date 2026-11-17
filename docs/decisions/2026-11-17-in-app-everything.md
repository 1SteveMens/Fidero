# Decision: the client app does everything itself

Date: 17 November 2026. Decided by the founder.

## What changed

The Tenmina client app no longer sends the person to the website to finish a task. Everything a client does on a phone is done inside the app:

| Task | Before | Now |
|---|---|---|
| Send a document a case manager asked for (SCR-PTL-13) | "Send documents on the Tenmina website" | Pick a file from Files or a photo from the library, sent through an evidence upload slot with its SHA-256 |
| Send the documents an errand needs (SCR-PTL-50) | Website | Same, on each checklist document |
| Photos and documents for a repair, files for a dispute statement | Website | Same, in the app |
| Read a released report, a family statement, a quote, a receipt or a photo | Report PDF opened in the browser; statements only on the website | A reader in the app: photos full screen with pinch to zoom, PDFs in the reader on iPhone, "Share or save" for the share sheet |
| Start a build in stages, a project fund, a managed property or an event | Website | New screens in the app |
| Verified listings | Website | A list and a listing page in the app, with photos, the report behind the badge, a question to the seller and reserving |
| Pay Tenmina's fee (SCR-APP-06) | In "web" mode, the portal's payment page in the browser | Inside the app, through the licensed payment provider: card or mobile money |

Exceptions, kept on purpose: the legal pages (terms, privacy) and the store link for "Update required" may open outside the app.

The development seed now sets `app.fee_payment_mode` to `in_app_provider`.

## Why

- A person abroad does this on a phone, often in a few spare minutes. Leaving the app, signing in on a website and coming back loses many of them.
- Store reviewers ask why an app links out for its core tasks (DQ-19).
- The same API, rules and evidence store sit behind both; nothing is weaker in the app. Every file is still hashed on the phone and checked by the server (FR-EVD-001), every link to a file still lasts 15 minutes or less (FR-EVD-003), and every approval still needs the client first and then two staff.

## Store rules for the fee

Tenmina's fee pays for work done in the real world: lawyers and surveyors search the records, visit the plot, survey it and write the report; agents queue at offices; inspectors visit building sites. Apple's App Store Review Guidelines (3.1.3(e), goods and services used outside the app) say such services must be paid with a method other than in-app purchase, such as a card form or a payment provider. Google Play's payments policy likewise lets apps take payment for physical services outside Google Play billing. So:

- The app takes Tenmina's fee only through the licensed payment provider (card or mobile money), inside the app. Never an in-app purchase.
- The report PDF is the record of that real-world work, not digital content sold on its own. If a reviewer sees it otherwise, the fallback is the provider's hosted checkout in a sheet inside the app, which the app already uses for a real provider.
- This is a reading of the rules, not legal advice. Q-23 stays open until the lawyer confirms it for both stores `[TO VERIFY]`.
- Purchase, building, project and family money is never paid in either app (RUL-01). It goes to the partner bank.

With the development payment provider, the checkout is a form in the app (a test card, or a mobile money prompt to approve). Nothing typed there leaves the phone; the provider's answer reaches Tenmina by its signed webhook. A real provider shows its own secure form in a sheet inside the app; Tenmina never sees or keeps a card number.

## What does not change

- Tenmina Field stays camera only for evidence (RUL-08). Only the client app may choose files and photos from the library, and only for subjects that accept uploaded files; the server refuses library files where RUL-08 applies.
- The portal keeps every one of these tasks for clients on a computer.
- Every rule in `CLAUDE.md`: Tenmina never holds client money; the client approves first, then two staff; silence is never approval; evidence is tamper-evident.

## Still to do

- Account screens: bank accounts, help and inviting a representative still point to the website. They change after the Face ID work on those screens is merged.
- "Forgot your password?" on the sign-in screen still opens the website, for the same reason.
- Tenmina Field: "My pay" statements still say they download on the website.
- The business plan doc: update the line on how the apps take fees.

## Documents updated

- `docs/specs/01-requirements-and-product-specification.md`: FR-APP-005, AS-14, Q-23 (v0.18).
- `docs/specs/03-ui-ux-design.md`: DA-11, DA-12, the client app sitemap, SCR-APP-06, DQ-19 (v0.12).
