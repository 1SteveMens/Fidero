# Testing the apps on your phone

How the founder runs the Fidero apps on an iPhone from a laptop, while the apps are being built. No developer account is needed for this. Commands work the same on a Mac (Terminal) and on Windows (PowerShell).

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

4. Get the code. Either install GitHub Desktop and clone the `Fidero` repository, or run:

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

2. Start the app:

   ```bash
   cd apps/client
   ```

   ```bash
   npx expo start
   ```

3. A QR code appears in the window. Point the iPhone's Camera at it and tap the banner. The app opens in Expo Go.
4. The laptop and the iPhone must be on the same Wi-Fi. If they are not, or the app does not load, stop it with Ctrl+C and start it with a tunnel instead:

   ```bash
   npx expo start --tunnel
   ```

5. Leave the window open while you test. Shake the iPhone for the menu, where "Reload" restarts the app.

If Expo Go says the project needs a different SDK version, tell Claude: Expo Go only runs the newest Expo version, and the project is then moved to it.

## What to try in the client app

All data is sample data. Nothing moves money.

- Welcome: tap "Get started".
- Home: swipe the account cards; open "Needs you".
- Approve the release for Plot 14, Kasoa: type any six digits, then press and hold the button until it fills.
- Family: open the hospital bill and approve it the same way.
- Property, Projects and Account tabs.
- Turn on Dark Mode, Reduce Motion and VoiceOver in the iPhone's Settings and try again. With VoiceOver, a double tap approves instead of holding.

## Reporting a problem

Take a screenshot and write down what you tapped just before. Paste both into the session. Say which phone and which iOS or Android version.

## Fidero Field and field users

Fidero Field runs in Expo Go the same way, from `apps/field`. Field users on Android install Expo Go from Google Play and scan the same QR code. Signing photos with the phone's secure chip needs a test build instead of Expo Go: an install file on Android, and on iPhone a build that needs the Apple Developer Program (`docs/decisions/2026-11-12-build-with-claude.md`).
