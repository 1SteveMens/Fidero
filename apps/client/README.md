# Tenmina client app

The **Tenmina** app for clients, family members and tenants, for iOS and Android (Apple App Store and Google Play from R2). Built with Expo SDK 58, React Native and Expo Router. Requirements: `docs/specs/01` (module APP and the client features it reuses); architecture: `docs/specs/02` ADR-22.

This first build runs on **sample data** from `@tenmina/shared` (`createSampleApi`). Nothing here moves money: approvals change sample state only, and the server will enforce every rule again.

## Design direction: Bloc

The founder chose **Bloc** on 12 November 2026. The full rules are in `docs/specs/03` section 6.1a, and the mockups in `docs/specs/03-mockups/bloc/`.

- Black or white grounds. Lime for proof and the main action, orange only for what needs the client, yellow only for the Amber verdict.
- Bricolage Grotesque for words and numbers, IBM Plex Mono for references, dates and labels (`@expo-google-fonts`).
- Money held at the bank shows as account cards side by side, each with a turning seal. No card network logo or chip.
- Approvals: a ticket with the amount and exactly who is paid, every condition ticked, the approval chain (you, two Tenmina staff, the bank), a six-box code, then **press and hold** for 1.2 seconds. With VoiceOver or TalkBack, a double tap approves.
- A Bloc tab bar on both platforms. Motion everywhere is short and stops when the phone asks for reduced motion.
- In system dark mode every screen is black.

Tokens live in `packages/tokens` (version 3). Components are in `src/components`: `ui.tsx` (text, panels, chips, steps, buttons, hold, code field), `money.tsx` (account cards, seal, ticket), `ApprovalSheet.tsx`, `TabBar.tsx` and `Mark.tsx`.

## Run it

From the repository root:

```bash
pnpm install
```

```bash
cd apps/client && npx expo start
```

Scan the QR code with Expo Go, or press `i` or `a` for a simulator. Web preview:

```bash
cd apps/client && npx expo export --platform web
```

## Checks

```bash
pnpm -r typecheck
```

```bash
pnpm -r test
```

## Screens

| Route | Screen |
|---|---|
| `/welcome`, `/sign-in`, `/sign-up` | Welcome; sign in with the authenticator code when MFA is on (SCR-PTL-03); sign up with email and phone codes (SCR-PTL-02, 37) |
| `/turn-on-notifications` | Turn on notifications? (SCR-APP-01); registers the install with `/v1/me/push-devices` |
| `/` | Home (SCR-PTL-36): account cards with the seal, quick actions, Needs you, everything else |
| `/property`, `/family`, `/projects`, `/account` | The other tabs |
| `/order` | Order a report in four steps with the site plan (SCR-PTL-06 to 09) |
| `/pay-fee/[id]` | Pay Tenmina's fee (SCR-APP-06): in `web` mode it opens the website checkout in the browser, never an in-app purchase |
| `/case/[id]`, `/report/[id]` | Case tracker and report viewer (SCR-PTL-12, 14) |
| `/escrow/[id]` | Escrow tracker, terms acceptance and the bank's own payment details (SCR-PTL-16 to 18) |
| `/release/[id]` | Approve any release from a held account: purchase, milestone, carer, errand fee (ticket, conditions, code, press and hold) |
| `/payee-change/[id]` | Approve a payee change (SCR-MOB-23) |
| `/invoice/[id]`, `/fee-payment/[id]` | Pay an invoice by either route, then the payment and its receipt (SCR-PTL-40) |
| `/member/[id]`, `/member/new` | Family-member statement, add a family member (SCR-PTL-42, 38) |
| `/care-plan/[id]`, `/care-visit/[id]`, `/concern/[id]` | Care plan with start and code, visits, concerns (SCR-PTL-43, 44) |
| `/errand/[id]`, `/errand/new` | Errand progress and catalogue (SCR-PTL-50, 49) |
| `/event/[id]` | Event budget, vendors and vendor payment approval |
| `/policy/[id]`, `/premium/[id]` | Policy wallet and premiums paid straight to the insurer (SCR-PTL-52) |
| `/project/[id]` | Build dashboard and project fund (SCR-PTL-22, 30) |
| `/managed/[id]`, `/repair/[id]` | Property dashboard and repair quote approval (SCR-PTL-47, 48) |
| `/dispute/[id]` | Dispute with statements (SCR-PTL-29) |
| `/inbox`, `/item` | Messages; anything without its own screen yet, with a link to the website |
| `/account/security`, `/account/notifications`, `/account/representatives`, `/account/data`, `/account/delete` | Authenticator set-up, channels, representatives, my data, delete my account (FR-APP-004) |

## Next

- Unlock with Face ID or fingerprint (SCR-APP-02, SCR-APP-03, FR-APP-003) with `expo-local-authentication`.
- Real push tokens with `expo-notifications` in a development build; this build registers a development token.
- Uploading documents asked for on a case or an errand (today on the website).
- A licensed photograph for the welcome screen (03 DQ-22).
