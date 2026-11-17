# Phone apps UI audit: findings and fixes

Tenmina (`apps/client`) and Tenmina Field (`apps/field`), 17 November 2026. The founder saw white text on white
backgrounds. This audit looked for that and every other UI and UX bug the two apps' screens can show.

## How it was checked

`scripts/ui-audit/apps.js` runs on each app's web export (React Native Web), against a seeded API:

1. Export each app: `EXPO_PUBLIC_API_URL=http://localhost:8121 npx expo export --platform web --output-dir <dir>`.
2. Run the API with `seed_dev` and `TENMINA_CORS_ORIGINS=http://localhost:8131,http://localhost:8132`, logging to a file.
3. `node scripts/ui-audit/apps.js --api-log <runserver log> --client-dist <dir> --field-dist <dir> [--shots <dir>]`
   (about 35 minutes with `--parallel 3`). `scripts/ui-audit/app-flows.js` walks the fee and set-aside flows.

The script serves both exports and signs in through each app's own sign-in screen as 2 clients (ama, kofi: the
SMS code is read from the API log) and 7 field roles (inspector, carer, agent, runner, and surveyor, lawyer and qs
with the authenticator). The Field app registers the phone as it does after a real sign-in. It opens every route
under `src/app`, presses rows, tabs and buttons to reach detail screens and sheets, and blocks every POST, PUT,
PATCH and DELETE while it explores, so nothing changes on the server. It checks each view at 390x844 and 375x667, in
light and dark colour scheme:

- contrast of every text node and icon against its real background (4.5:1, 3:1 for large text and icons), and text drawn in its ground's colour (under 1.3:1, reported as "invisible-text")
- horizontal overflow and text cut off by its container, overlapping text
- touch targets under 44 x 44
- empty screens, screens still loading after 30 s, broken images
- "undefined", "null" or "NaN" shown, raw ids, code words or JSON shown
- console errors, page errors and failed API calls (for information)

The SMS limit (3 codes in 10 minutes, 10 a day) is enforced by the API. For repeated runs in the development
database, earlier codes of the two seeded clients were moved back two days before each run. The limit itself is unchanged.

## Results

Both runs use the final script, the same seeded data and the same 11 people. "Before" is the apps as they were at
the start (commit `c28c084`); "after" is this commit. The full output of the last run is in `apps-results.md`.

| Check | Before | After |
|---|---|---|
| Text drawn in its ground's colour (invisible) | 29 | 0 |
| Contrast under 4.5:1 (3:1 for large text and icons) | 53 | 0 |
| Touch targets under 44 x 44 | 51 | 0 |
| Overlapping text | 6 | 0 |
| Text cut off | 2 | 0 |
| Still loading (step bars read as spinners) | 3 | 0 |
| Horizontal overflow, empty screens, broken images, "undefined"/"NaN", raw ids or JSON, dead links | 0 | 0 |
| **Blocking findings** | **144** | **0** |
| Screens visited (views with sheets and in-place changes) | 197 (265) | 200 (267) |

A finding is one element on one screen for one person, merged across the four modes. A few "before" findings on
Home and Money are the seal's decorative words, now hidden from screen readers. The 6 API 404s left (for information)
are expected: kofi has no Tenmina account yet (the screens say "No account yet"), and some demo escrows are not
commitments, or point at a case the seed does not create.

Before and after, dark mode, 390x844 (`docs/screenshots/ui-audit/apps/`):

| Screen | Before | After |
|---|---|---|
| Client, case: "Latest" status | `client-case-dark-before.png` (white on white) | `client-case-dark-after.png` |
| Field, inspection: conflict line and check-in map | `field-job-conflict-strip-dark-before.png` (white strip, "Address" covered) | `field-job-conflict-strip-dark-after.png` |
| Field, My pay: agreement strip | `field-my-pay-dark-before.png` (white on white, bright lines) | `field-my-pay-dark-after.png` |

## What was wrong, and the fix

### 1. Text took the screen's colours, not the colours of the block it sat on (the founder's bug)

**Seen:** in dark mode, white text on white strips: the "Latest" status on a case, "We pay hospitals…" on Family,
"Reserve it" on a listing, the pay-in details on Money, escrow, premium and fee screens, "Your agreement" on Field's
My pay, the conflict line ("You have no link to the contractor…") and the search line on Field jobs. Grey text on white
(2.4:1) and lime icons on white (1.4:1) in the same strips. White "Send it from" on orange in dark mode. In light mode,
inside the black "start the plan" panel of a care plan, the code boxes and their labels were black on black.

**Cause:** `Panel tone="raised"` (the black strip) turned white in dark mode, because it used the palette's
`raised` colour, while every screen hard-coded its text as `#F7F6F2`. More generally, `T`, `Label`, `Button`,
`ListRow`, `Input` and `SecondFactorInput` always took the screen's palette. Inside a block of another colour
(a black strip on white, an orange or lime card, the white ticket on a black sheet) they drew the screen's text colour.

**Fix (`packages/ui`, `packages/tokens`):**
- A `PaletteContext`. Every `Panel` of another colour (raised, lime, orange, Amber, red) and the `Ticket` gives
  its contents its own palette, and `Screen` resets it. Components read it through `usePalette()`, so text, labels,
  buttons, rows and code boxes inside a block are always legible on it.
- The block palettes live in `packages/tokens` (`blocks`, `blockBackground`), with a test that every text and muted
  text colour reaches 4.5:1 on its block (`packages/mobile/test/palettes.test.ts`).
- The black strip stays black in dark mode: `#242424` on the black screen, not white. Lime and orange stay
  legible on it, and money screens stay on black as 6.1a says.
- The account card is `#1A1A1A` on a black screen, so it still reads as a card in dark mode.
- Hard-coded `#F7F6F2` and `#A9A69E` removed from the strips in 13 screens. They now take the block's palette.

### 2. Colours hard-coded for a white ground

- Icons drawn in `brand.ink`, or with no colour at all (which is black), on panels: Field queue rows and "Nothing
  waiting", the Field pay notice, the order "lock" line, the escrow "fresh search" line. They were black on `#1A1A1A`
  in dark mode (1.1:1 to 1.2:1). They now use the palette's text colour.
- Row lines and empty step circles hard-coded `#ECEAE4` and `#D6D3CB` in 12 screens showed as bright lines on black.
  They now use the palette's `line` and `lineStrong`.
- The unmatched bank-account name used `#B3261E` on dark panels (2.7:1). A new token `redText` is `#B3261E` on white
  and `#FF5A4E` on black. Red is still used only for an unmatched payee name.
- The case step count "/9" was drawn in the line colour (1.5:1). It is now muted text (5.6:1).
- The family chevron used `#6A675F` on any ground. It now uses the palette.
- Field check-in errors were orange text on a light panel (2.5:1), against 6.1a. They are now plain text with an alert icon.

### 3. Touch targets under 44 points

- `Choice` rows (event type, errand "For me", family relationship, inspection result, payment method) were 40 high: now 44.
- Field inspection "Not applicable" was 32 high with no spoken name: now 44 x 44 and says which check it answers.
- Switches (client notification channels, Field "pretend there is no signal") were 40 x 20 on the web. They are now
  `SwitchRow`: the whole 56-point row toggles the setting and is announced as a switch with its state.

### 4. Layout

- Field check-in map: the position strip covered the "Address" mark when its text wrapped to two lines. The map is
  taller and its marks sit above the strip.
- Client welcome at 375x667: the turning seal ran under the "Released only on proof" badge. The seal is now sized to
  fit above the badge.
- The seal's turning words are decoration. They are hidden from screen readers, as the same words are on the card.
- Account card rows: a long commitment name could push the amount column. The name column can now shrink and
  ends in "…".
- White and surface chips ("In run", "Being checked") on a ground of the same colour had no visible edge. They now
  have a thin outline.
- `InlineApproval` (event vendors, repair quotes) was a black panel on a black screen in dark mode, with no edge. It
  is now the black strip.

### 5. Screens that left the person without a next step

- **Fee payment, a payment started and left (`pay-fee/[id]`).** Once a card or mobile money payment had been started
  and not finished, the API refuses a second one (`can_pay` false). The screen showed only a greyed-out "Pay by card"
  button, with no reason and no way back. The order now names its open payment (`open_payment`: id, method, status,
  checkout link: API change below), and the screen says "You started paying by card and did not finish", with
  "Continue the payment", which reopens the in-app checkout or the provider's sheet.
- **Fee payment, a draft order.** "Before you can pay" joined objects into text, so it would have shown
  "[object Object]". It now lists the messages.
- **A project being set up (`project/[id]`)** showed "0 of 0 milestones paid" and an empty grey strip under
  Milestones. It now says "No milestones yet" and why, and hides the empty progress bar.
- **Links that need the client ended at a summary.** Home and inbox items link to API paths. Some had no
  app route, so they opened the summary screen (`/item`), which offers no action. "Please approve GHS 9,000.00 to
  Accra Funeral Home" (`/vendor-payments/…`) and "Reserved: … Accept the escrow terms" (`/reservations/…`) were dead
  ends for an approval. `/item` now looks the record up and goes to the screen where the client acts: the event,
  with its inline approval, and the reservation's escrow, or its listing. Event receipts, bank accounts and data
  requests now open their own screens (`apps/client/src/lib.ts`, with tests). The summary's label was the raw path
  ("vendor payments", "partner orders"). It is now a word such as "Event payment", or nothing.
- **A record that is not there (404)** showed "Not found." and "Try again", which can never work. Every screen now
  says "We could not find this", why that can happen, and "Go back" (`LoadState` in `packages/mobile`). It showed
  for the demo escrow "Plot at Kwabenya (proposed)": its "Open the case" points at a case id the seed never creates
  (`api/escrow/seed.py` gives demo escrows placeholder case ids). That is seed data, not app behaviour, and was
  left as it is.
- **Step bars (`SegBar`, `DotStepper`)** had no value on the web (React Native Web drops `accessibilityValue`), so a
  screen reader announced each as an unknown busy indicator. They now carry `aria-valuenow`, `aria-valuemax` and a
  spoken text such as "Step 1 of 4: What".

### 6. API change

`api/orders/serializers.py`: `OrderSerializer.open_payment`, the payment the client started and has not finished (or
null), so the app can take them back to it. Read-only, and it changes no rule: a second payment is still refused while
one is open. Test: `orders/tests/test_orders.py::test_open_payment_is_named_so_the_app_can_resume_it`.
`packages/api-client/openapi.yaml` and `src/schema.d.ts` regenerated.

### 7. Audit false positives found and fixed in the script (not app bugs)

- "Still loading" on Home, Family, Projects and Property: the script took the app's start screen for a settled
  screen and checked too early. It now waits for two quiet checks in a row and names the API calls still in flight.
- The token refresh was blocked with the other POSTs during long runs. It is now let through.
- A one-line name ending in "…" was measured at its full width and counted as overlapping its neighbour.
- A photo (drawn as a background image) or a PDF frame alone counted as an empty screen.
- A step bar at step 0 counted as a spinner (fixed in the app as well, above).

## Recent flows on the phone layouts

Walked in Chromium with Playwright as ama by `scripts/ui-audit/app-flows.js`, screenshots checked by eye:

| Flow | Size | Result |
|---|---|---|
| Sign-in with the SMS code (code read from the API log), then the Face ID offer (skipped: no biometrics on the web) | 390x844 | Works. Every audit run signs in this way |
| One-account Home: the account card, its commitments, "Needs you", in light and dark | 390x844, 375x667 | Works. Card reads as a card in dark mode |
| `/money`: account card with 12 commitments, set-aside prompts, pay-in details on the black strip | 390x844, 375x667 | Works. Pay-in details were white on white in dark mode before |
| Set money aside: `/set-aside/[id]` sheet, ticket, checks, "Send me a code", SMS code, press and hold | 390x844 | Works end to end: "Your approval is in", with a code by text message |
| Approval with the code fallback (`invoice/[id]`, `release/[id]`): the code path the web uses instead of Face ID | 390x844 | Works. Face ID itself needs the iPhone |
| In-app documents: case documents and the file viewer (`file/[id]`) for a JPEG and a PDF | 390x844 | Image shows. The signed links return the real files. The PDF frame is empty in headless Chromium only |
| In-app fee checkout: `pay-fee/[id]`, card, the in-app test checkout, paid | 375x667 | Works, after the fix for a payment left open |

## Only a real iPhone can confirm

- Face ID itself: the web build has no biometrics, so approvals there fall back to the code by text message.
  Approving with Face ID, cancelling it, the fallback after 3 cancels, and the "Use the code instead" line need
  the iPhone (`docs/operations/testing-the-apps.md`).
- The native sheet presentation (`formSheet`, the grabber, the 0.96 detent) of release, invoice, set-aside and payee
  change. The web shows them as full screens.
- The PDF reader: headless Chromium shows an empty frame for PDFs. On iOS the file screen uses a WebView, and on
  Android it offers Share or save.
- Haptics, the hold-to-approve feel, safe-area insets and the home indicator under the footer buttons.
- Dark mode switching while the app is open, and the system font scaling (Dynamic Type) at large sizes.
- Touch targets measured here are web sizes. A native switch is no longer used, and no other control is under 44 points.
- SMS sign-in on a real number with one-time-code autofill from the Messages app.
- Contrast in strong sun on Field phones (6.1c): the colours pass 4.5:1, but glare is a field test.

## Not reached by the crawler

From the seeded data the crawler reached every route except these, which need data the seed does not give the
person, or an action the crawler blocks:

- Client: `/checkout/[id]` (needs a payment started, a POST; walked by `app-flows.js` instead), `/payee-change/[id]`
  (no payee change waiting for ama), `/concern/[id]` (no care concern raised), `/face-id` and
  `/turn-on-notifications` (shown once after sign-in, and skipped on the web, which has no biometrics or push).
  Kofi reaches fewer screens because he has fewer records; every screen he lacks was reached as ama.
- Field: `/errand/[id]` (the seed gives the errand agent no errand), `/pay/[id]` for the inspector, carer, agent and
  qs (no payables yet), `/job/[type]/[id]` for the lawyer and qs (no job assigned).

These screens use the same components and palettes as the screens checked, so the colour fixes apply to them. Their
layout was not checked by the script.
