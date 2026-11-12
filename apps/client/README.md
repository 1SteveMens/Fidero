# Fidero client app

The **Fidero** app for clients, family members and tenants, for iOS and Android (Apple App Store and Google Play from R2). Built with Expo SDK 58, React Native and Expo Router. Requirements: `docs/specs/01` (module APP and the client features it reuses); architecture: `docs/specs/02` ADR-22.

This first build runs on **sample data** from `@fidero/shared` (`createSampleApi`). Nothing here moves money: approvals change sample state only, and the server will enforce every rule again.

## Design direction

Current, native chrome with a Fidero layer on top:

- Native tab bar (`expo-router/native-tabs`): Liquid Glass on iOS 26, Material 3 on Android. The web preview uses a floating bottom bar instead (`(tabs)/_layout.web.tsx`).
- Large in-content titles, borderless cards with soft depth, 20-point corners.
- A deep indigo hero for money held at the bank, in both themes.
- Approvals open as sheets: amount, exactly who is paid, the bank's name check, every condition, a 6-box code field, then the three steps (you, two Fidero staff, the bank). Haptic feedback on approve.
- Verdicts always show icon, word and colour together. Full dark mode.

Tokens live in `packages/tokens`.

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
pnpm --filter @fidero/shared test
```

## Screens

| Route | Screen |
|---|---|
| `/` | Home: money held, what needs you, property, family, projects |
| `/property`, `/family`, `/projects`, `/account` | The other tabs |
| `/case/[id]` | Case progress and timeline |
| `/report/[id]` | Report verdict, conditions, section results, PDF fingerprint |
| `/escrow/[id]` | Release approval sheet |
| `/invoice/[id]` | Institution invoice approval sheet |
| `/account/delete` | In-app account deletion: what is deleted, what is kept and why (FR-APP-004) |

## Next

- Replace the sample API with the HTTP client for `/v1` once the R1 backend exists.
- Sign-in, push notifications (FR-APP-002), biometric unlock (FR-APP-003), minimum-version check (FR-APP-006).
- Fidero Field in `apps/field`, with the native capture, signing and attestation modules.
