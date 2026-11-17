#!/usr/bin/env node
/*
 * Walks the client app's recently changed money flows on phone sizes, on the web export, and saves a screenshot
 * of each step: Tenmina's fee paid in the app (pay-fee, then the in-app checkout, at 375x667), the one account
 * (/money), and setting money aside with a code by text message and press and hold (at 390x844). It changes data:
 * run it only against a development database.
 *
 * Usage (API running with seed_dev and logging to a file, the client export served on --port, see apps.js):
 *   node scripts/ui-audit/app-flows.js --api-log <runserver log> --port 8131 --order <order id awaiting payment> \
 *     --commitment <commitment id that can take money> --out <dir> [--email ama@example.com]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const API = (args.api || 'http://localhost:8121').replace(/\/$/, '');
const LOG = args['api-log'];
const OUT = args.out || 'app-flows';
const EMAIL = args.email || 'ama@example.com';

function codeAfter(offset) {
  const m = [...fs.readFileSync(LOG, 'utf8').slice(offset).matchAll(/\[sms\] to [^:]+: .*?\b(\d{6})\b/g)];
  return m.length ? m[m.length - 1][1] : null;
}

/* Sign in through the API: password, then the code the console SMS adapter printed. */
async function token() {
  const post = (body) => fetch(`${API}/v1/auth/token`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Tenmina-App': 'client/ios/1.0.0' }, body: JSON.stringify(body) });
  const offset = fs.statSync(LOG).size;
  let r = await post({ identifier: EMAIL, password: 'tenmina-dev-123' });
  if (r.status === 401) {
    await new Promise((s) => setTimeout(s, 800));
    r = await post({ identifier: EMAIL, password: 'tenmina-dev-123', code: codeAfter(offset) });
  }
  if (!r.ok) throw new Error(`sign-in failed: ${r.status} ${await r.text()}`);
  return r.json();
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const t = await token();
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 667 }, reducedMotion: 'reduce' });
  await ctx.addInitScript((tok) => { if (!localStorage.getItem('tenmina.tokens')) localStorage.setItem('tenmina.tokens', JSON.stringify({ access: tok.access, refresh: tok.refresh, expiresAt: Date.now() + tok.expires_in * 1000 })); }, t);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => console.log('page error:', e.message));
  p.on('response', (r) => { if (r.url().startsWith(API) && r.status() >= 400) console.log('api', r.status(), r.request().method(), new URL(r.url()).pathname); });
  const base = `http://localhost:${args.port || 8131}`;
  const step = async (name) => {
    await p.waitForTimeout(1800);
    await p.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log(`${name}: ${p.url().replace(base, '')} | ${(await p.innerText('body')).replace(/\s+/g, ' ').slice(0, 160)}`);
  };
  const press = (re) => p.getByRole('button', { name: re }).first().click();

  // 1. Tenmina's fee in the app: continue a payment left open, or start one by card; pay with the test card.
  await p.goto(`${base}/pay-fee/${args.order}`);
  await step('1-pay-fee');
  if (await p.getByRole('button', { name: /Continue the payment$/ }).count()) await press(/Continue the payment$/);
  else await press(/Pay by card$/);
  await step('2-checkout');
  await p.getByLabel('Card number').fill('4242424242424242');
  await p.getByLabel('Expiry').fill('1230');
  await p.getByLabel('Security code').fill('123');
  await press(/^\W*Pay [A-Z]{3} /);
  await step('3-checkout-paid');

  // 2. The one account, then set money aside: a code by text message, then press and hold.
  await p.setViewportSize({ width: 390, height: 844 });
  await p.goto(`${base}/money`);
  await step('4-money');
  await p.goto(`${base}/set-aside/${args.commitment}`);
  await step('5-set-aside');
  const offset = fs.statSync(LOG).size;
  await press(/Send me a code$/);
  await p.waitForTimeout(1500);
  const code = codeAfter(offset);
  if (!code) throw new Error('no SMS code in the API log');
  await p.getByRole('textbox', { name: /^Code from/ }).first().fill(code);
  await step('6-set-aside-code');
  const box = await p.getByRole('button', { name: /^Approve|hold/i }).first().boundingBox();
  await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await p.mouse.down();
  await p.waitForTimeout(1600);
  await p.mouse.up();
  await step('7-set-aside-done');
  await p.emulateMedia({ colorScheme: 'dark' });
  await step('8-set-aside-done-dark');
  await browser.close();
})();
