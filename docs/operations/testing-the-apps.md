# Testing the apps on your phone

How the founder runs the Tenmina apps on an iPhone from a laptop, while the apps are being built. No developer account is needed for this. Commands work the same on a Mac (Terminal) and on Windows (PowerShell).

## Once: set up the laptop

1. Install **Node.js**, the LTS version, from https://nodejs.org.
2. Open a new Terminal (Mac) or PowerShell (Windows) window and check that Node is installed. It should print a version number:

   ```bash
   node -v
   ```

   If it says "not found", close the window, open a new one and try again. If it still fails, run the Node.js installer again.

3. Install pnpm, the package tool this project uses:

   ```bash
   npm install -g pnpm@10.28.0
   ```

   On a Mac, if this ends with "permission denied", run it again with `sudo` in front and type your Mac password:

   ```bash
   sudo npm install -g pnpm@10.28.0
   ```

   Check it with `pnpm -v`, which should print `10.28.0`. (Older guides use `corepack enable` instead; newer Node versions no longer include corepack.)

4. Get the code. Either install GitHub Desktop and clone the `Tenmina` repository, or run:

   ```bash
   git clone https://github.com/1SteveMens/Fidero.git
   ```

5. Go into the folder and switch to the working branch:

   ```bash
   cd Fidero
   ```

   ```bash
   git checkout claude/quirky-wozniak-an94wx
   ```

6. Install everything the apps need. This takes a few minutes the first time:

   ```bash
   pnpm install
   ```

## Once: set up the iPhone

Install **Expo Go** from the App Store. It is free.

## Each time you test the client app

1. Get the latest code:

   ```bash
   git pull
   ```

   ```bash
   pnpm install
   ```

2. Start the API on the laptop, reachable from the phone (in its own Terminal window; see `api/README.md` for the first-time database setup):

   ```bash
   cd api
   ```

   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

   Find the laptop's address on the Wi-Fi (on a Mac: System Settings, Wi-Fi, Details, for example `192.168.1.20`). The phone cannot use "localhost".

3. Start the app, pointing it at the API:

   ```bash
   cd apps/client
   ```

   ```bash
   EXPO_PUBLIC_API_URL=http://192.168.1.20:8000 npx expo start
   ```

4. A QR code appears in the window. Point the iPhone's Camera at it and tap the banner. The app opens in Expo Go.
5. The laptop and the iPhone must be on the same Wi-Fi. If they are not, or the app does not load, stop it with Ctrl+C and start it with a tunnel instead:

   ```bash
   npx expo start --tunnel
   ```

6. Leave the window open while you test. Shake the iPhone for the menu, where "Reload" restarts the app.

If Expo Go says the project needs a different SDK version, tell Claude: Expo Go only runs the newest Expo version, and the project is then moved to it.

## What to try in the client app

The app now uses the development API and its seeded data. Nothing moves real money: the bank is a fake.

- Sign in as `ama@example.com`, password `tenmina-dev-123`.
- Account, Authenticator app: set one up (Google Authenticator or 1Password). Every approval needs its code.
- Home: the one Tenmina account card with its commitments; open a commitment and "Set aside from my balance"; open "Needs you".
- Family: open the hospital bill, enter the code, then press and hold the button until it fills.
- Projects: open "Boys' quarters at Kasoa" and approve the Foundation payment the same way.
- Property, then "Check a plot": go through the four steps with a photo of any site plan; the fee opens the Tenmina website.
- Account, Delete my account: read it, but do not confirm on your own account.
- Turn on Dark Mode, Reduce Motion and VoiceOver in the iPhone's Settings and try again. With VoiceOver, a double tap approves instead of holding.

### Face ID for approvals (FR-ACC-014)

In Expo Go, the Face ID permission question names Expo Go, not Tenmina. That is expected; the store build shows Tenmina's own text.

1. Set up the authenticator first (Account, Authenticator app). Sign out and sign in again with the code.
2. After sign-in the app offers "Use Face ID for approvals". Tap it, allow Face ID for Expo Go, and look at the phone. If it asks for the code, enter it once.
3. Family: open the hospital bill. There are no code boxes now: press and hold, then Face ID. The approval goes, and the next screen says "with Face ID".
4. Open the next approval, hold, and cancel Face ID once: nothing is approved and it says so. Cancel three times: the six code boxes appear. Approve with the code.
5. On an approval, tap "Use the code instead": the code boxes appear.
6. Account, "Face ID or fingerprint for approvals": this phone shows as on. Tap "Turn off on this phone", then approve something: it asks for the code again. Turn it back on from the same screen.
7. Cover the camera or turn Face ID off for Expo Go in the iPhone's Settings, then approve: the app falls back to the code.
8. Optional: reset your password on the website and sign in again. The next approval says Face ID was turned off for this phone and asks for the code; Account shows no phones until you turn it on again.

## If the app stays on "Connecting to Tenmina…" or a sign-in fails

The app shows "Connecting to Tenmina…" and the address it is trying when it cannot reach the API. Check the connection from the phone itself:

1. On the iPhone, open Safari and go to `http://<laptop address>:8000/health`, for example `http://192.168.1.20:8000/health`.
2. If it shows `{"status":"ok"}`, the connection works. Stop Expo with Ctrl+C and start it again with `npx expo start -c` (keep `EXPO_PUBLIC_API_URL=...` in front).
3. If it does not load:
   - The API window must say `0.0.0.0:8000`. If not, stop it and run `python manage.py runserver 0.0.0.0:8000`.
   - Check the address with `ipconfig getifaddr en0` on the Mac.
   - Allow Python through the Mac's firewall (System Settings, Network, Firewall), or turn the firewall off while testing.
   - The phone and the Mac must be on the same Wi-Fi, not a guest network.

## Reporting a problem

Take a screenshot and write down what you tapped just before. Paste both into the session. Say which phone and which iOS or Android version.

## Tenmina Field

Start it the same way, from its own folder:

```bash
cd apps/field
```

```bash
npx expo start
```

Start it with the same `EXPO_PUBLIC_API_URL=...` in front. Stop the client app first with Ctrl+C, or run Tenmina Field in a second Terminal window. Sign in as a seeded field user (password `tenmina-dev-123`); the phone then registers its own signing key:

- **Inspector** `inspector@example.com`: open "Inspect foundation, East Legon", check in, answer each check, mark one "No" as a defect with a photo and a value, then choose a result.
- **Contractor** `builder@example.com`: open a milestone, take the evidence photos (and the video), then submit. Try it with "Test: pretend there is no signal" switched on in Account, and watch the Queue tab.
- **Carer** `carer@example.com`: open "Visit Akosua Mensah", check in (far from the address, it asks you to say why), record each plan item and the blood pressure, then check out. The family's code goes to their phone, not yours.
- **Runner** `runner@example.com`: a case task with the search notice, a bill to collect, and the Pay tab.
- **Errand agent** `kofi.agent@example.com`: the birth certificate errand and its steps.

The first time, the phone asks for the camera and for your location. Allow both: the app needs them to seal where and when evidence was taken.

Field users on Android install Expo Go from Google Play and scan the same QR code. This build signs with a software key kept in the phone's keychain. Signing with the phone's secure chip (and real App Attest or Play Integrity) will need a test build instead of Expo Go: an install file on Android, and on iPhone a build that needs the Apple Developer Program (`docs/decisions/2026-11-12-build-with-claude.md`).
