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
| `/welcome` | Welcome and sign in (demo: any button signs in) |
| `/` | Home: account cards, quick actions, what needs you, cases and family |
| `/property`, `/family`, `/projects`, `/account` | The other tabs |
| `/case/[id]` | Case progress as a step trail |
| `/report/[id]` | Report verdict, conditions, section results, PDF fingerprint |
| `/escrow/[id]` | Release approval: ticket, conditions, code, press and hold |
| `/invoice/[id]` | Institution invoice approval sheet |
| `/account/delete` | In-app account deletion: what is deleted, what is kept and why (FR-APP-004) |

## Next

- Replace the sample API with the HTTP client for `/v1` once the R1 backend exists.
- Real sign-in (FR-ACC-001 to FR-ACC-003), push notifications (FR-APP-002), biometric unlock (FR-APP-003), minimum-version check (FR-APP-006).
- A licensed photograph for the welcome screen (03 DQ-22).
- Tenmina Field in `apps/field`, with the native capture, signing and attestation modules.
