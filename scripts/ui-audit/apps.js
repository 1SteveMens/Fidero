#!/usr/bin/env node
/*
 * UI audit for the two phone apps, Tenmina (apps/client) and Tenmina Field
 * (apps/field), run on their web export (React Native Web) in Chromium.
 *
 * It serves each exported app, signs in through the app's own sign-in screen as
 * each seeded person (an SMS code is read from the API's log, where the console
 * SMS adapter prints it; an authenticator code is computed from the development
 * secret), visits every route under `src/app`, presses list rows, tabs and
 * buttons to reach detail screens and sheets (with every POST, PUT, PATCH and
 * DELETE to the API blocked while it explores, so nothing changes), then opens
 * the screens it did not reach from the links the API gives that person (home
 * rows and notifications, payables, errands and field jobs), and on each
 * view, at 390x844 and 375x667, in light and dark colour scheme, checks:
 *   - contrast of every visible text node against its effective background
 *     (4.5:1, or 3:1 for large text; icons 3:1), and text drawn in the colour of its ground
 *   - horizontal overflow, and text cut off by its container
 *   - overlapping text
 *   - touch targets under 44 x 44
 *   - empty screens with no empty state, and screens still loading after 10 s
 *   - broken images, "undefined" / "null" / "NaN" shown as text, raw ids, codes or JSON
 *   - console errors, page errors and failed API calls
 *
 * Usage (API running with `seed_dev`, both apps exported for web with
 * EXPO_PUBLIC_API_URL pointing at it, and the API's CORS list allowing the two ports):
 *   node scripts/ui-audit/apps.js --api http://localhost:8121 --api-log /path/to/runserver.log \
 *     --client-dist /path/to/client-export --field-dist /path/to/field-export \
 *     [--app client|field] [--roles ama,inspector] [--max 120] [--out scripts/ui-audit/apps-report.md] \
 *     [--json path.json] [--shots dir] [--parallel 3] [--trace 1]
 *
 * The API allows 3 SMS codes in 10 minutes and 10 a day per person. Each run asks for one code for each of the two
 * clients; for repeated runs against a development database, move their earlier codes back first, for example
 * `UPDATE acc_one_time_code SET created_at = created_at - interval '2 days' WHERE person_id IN (SELECT id FROM
 * acc_person WHERE email IN ('ama@example.com', 'kofi@example.com'))`. Findings and fixes: apps-report.md.
 *
 * Playwright comes from the machine (`require('playwright')`).
 */
'use strict';
const fs = require('fs');
const http = require('http');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => {
    if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : 'true']);
    return acc;
  }, []),
);
const API = (args.api || 'http://localhost:8121').replace(/\/$/, '');
const API_LOG = args['api-log'];
const PASSWORD = 'tenmina-dev-123';
const MFA_SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'; // DEV_MFA_SECRET in api/accounts/seed.py
const MAX_VIEWS = Number(args.max || 120);
const MAX_CLICKS = Number(args.clicks || 30);
const SETTLE_MS = Number(args.settle || 10000);
const MODES = [
  { name: '390 light', width: 390, height: 844, scheme: 'light' },
  { name: '390 dark', width: 390, height: 844, scheme: 'dark' },
  { name: '375 light', width: 375, height: 667, scheme: 'light' },
  { name: '375 dark', width: 375, height: 667, scheme: 'dark' },
];
const APPS = {
  client: { dir: 'client', dist: args['client-dist'], port: Number(args['client-port'] || 8131) },
  field: { dir: 'field', dist: args['field-dist'], port: Number(args['field-port'] || 8132) },
};

/* Seeded people (api/accounts/seed.py). `mfa`: the authenticator; `sms`: a code by text message. */
const ROLES = [
  { app: 'client', key: 'public', email: null },
  { app: 'client', key: 'ama', email: 'ama@example.com', sms: true },
  { app: 'client', key: 'kofi', email: 'kofi@example.com', sms: true },
  { app: 'field', key: 'public', email: null },
  { app: 'field', key: 'inspector', email: 'inspector@example.com' },
  { app: 'field', key: 'carer', email: 'carer@example.com' },
  { app: 'field', key: 'agent', email: 'agent@example.com' },
  /* the errand agent on the panel, with errands and pay (Yaa's vetting is still pending, so she has none) */
  { app: 'field', key: 'errand-agent', email: 'kofi.agent@example.com' },
  { app: 'field', key: 'runner', email: 'runner@example.com' },
  { app: 'field', key: 'surveyor', email: 'surveyor@example.com', mfa: true },
  { app: 'field', key: 'lawyer', email: 'lawyer@example.com', mfa: true },
  { app: 'field', key: 'qs', email: 'qs@example.com', mfa: true },
];
/* Screens a signed-out person can open. */
const PUBLIC = { client: ['/welcome', '/sign-in', '/sign-up', '/forgot-password', '/help'], field: ['/welcome', '/forgot-password', '/help'] };
/* Buttons the crawler never presses: they end the session or leave the app. */
const NEVER_PRESS = /sign out|log out|delete my|delete this|^remove|use a different account|open the store|call |email us|whatsapp|share|download|open in|^back$|close the camera/i;

function totp(secret, t = Date.now()) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const c of secret.replace(/=+$/, '')) bits += alphabet.indexOf(c).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(t / 30000)));
  const h = crypto.createHmac('sha1', key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0');
}

/* Routes from the expo-router app folder: [{pattern, re, dynamic}] */
function routes(app) {
  const dir = path.join(ROOT, 'apps', app, 'src', 'app');
  const out = [];
  (function walk(d, rel) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.isDirectory()) walk(path.join(d, e.name), [...rel, e.name]);
      else if (/\.tsx$/.test(e.name) && !e.name.startsWith('_')) {
        const name = e.name.replace(/\.tsx$/, '');
        const parts = [...rel, name].filter((s) => !/^\(.*\)$/.test(s) && s !== 'index');
        const url = '/' + parts.join('/');
        const re = new RegExp('^' + url.replace(/\[[^\]]+\]/g, '[^/]+') + '/?$');
        out.push({ pattern: url, re, dynamic: url.includes('[') });
      }
    }
  })(dir, []);
  return out;
}

/* A static file server with the single-page fallback the web export needs. */
function serve(dist, port) {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.ico': 'image/x-icon', '.ttf': 'font/ttf', '.svg': 'image/svg+xml' };
  const server = http.createServer((req, res) => {
    const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let file = path.join(dist, p);
    if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, 'index.html');
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(port, () => resolve(server)));
}

/* ---------- in-page checks (run inside the browser) ---------- */
function viewChecks() {
  const parse = (c) => {
    const m = c && c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map((x) => (x.endsWith('%') ? parseFloat(x) / 100 : Number(x)));
    return [p[0], p[1], p[2], p[3] === undefined ? 1 : p[3]];
  };
  const over = (fg, bg) => {
    const a = fg[3];
    return [fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a), fg[2] * a + bg[2] * (1 - a), 1];
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  /* A short, stable description of where an element is: its nearest labelled ancestor and its own text. */
  const desc = (el) => {
    const parts = [];
    for (let e = el, i = 0; e && e.nodeType === 1 && i < 6 && e !== document.body; e = e.parentElement, i++) {
      const label = e.getAttribute('aria-label');
      const role = e.getAttribute('role');
      if (label || (role && role !== 'presentation')) parts.unshift(`${role || e.tagName.toLowerCase()}${label ? `"${label.slice(0, 30)}"` : ''}`);
      if (parts.length >= 2) break;
    }
    return parts.join(' > ') || el.tagName.toLowerCase();
  };
  const hidden = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return true;
      if (e.getAttribute('aria-hidden') === 'true' && e !== el && e.getAttribute('role') !== 'img') {
        /* react-navigation hides screens under the current one with aria-hidden */
        if (e.style && (e.style.pointerEvents === 'none' || cs.pointerEvents === 'none')) return true;
      }
    }
    return false;
  };
  /* The visible rectangle after clipping by ancestors that clip. Scroll containers clip only content scrolled away, which is not a bug. */
  const clipRect = (el, r) => {
    let { left, top, right, bottom } = r;
    let clippedBy = null;
    /* the text's own element clips too: a one-line name ends in "…" and its hidden part is not on screen */
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const b = e.getBoundingClientRect();
      const own = e === el;
      if (own && cs.overflowX !== 'visible') { left = Math.max(left, b.left); right = Math.min(right, b.right); }
      if (own && cs.overflowY !== 'visible') { top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom); }
      if (own) continue;
      if (cs.overflowX !== 'visible') {
        if (right > b.right + 1 && cs.overflowX !== 'auto' && cs.overflowX !== 'scroll') clippedBy = clippedBy || e;
        left = Math.max(left, b.left); right = Math.min(right, b.right);
      }
      if (cs.overflowY !== 'visible') {
        if (bottom > b.bottom + 1 && top < b.bottom - 1 && cs.overflowY !== 'auto' && cs.overflowY !== 'scroll') clippedBy = clippedBy || e;
        top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom);
      }
    }
    return { left, top, right, bottom, w: right - left, h: bottom - top, clippedBy };
  };
  const scrollsX = (el) => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const ox = getComputedStyle(e).overflowX;
      if ((ox === 'auto' || ox === 'scroll') && e.scrollWidth > e.clientWidth + 1) return true;
    }
    return false;
  };
  const background = (el) => {
    const layers = [];
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== 'none' && !/gradient/.test(cs.backgroundImage)) return { unknown: 'image' };
      if (e.tagName === 'IMG' || e.tagName === 'VIDEO' || e.tagName === 'CANVAS') return { unknown: e.tagName };
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) {
        layers.push(c);
        if (c[3] >= 1) break;
      }
    }
    let bg = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
    return { color: bg };
  };
  const opacityOf = (el) => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; };
  const isIcon = (el, text) => /^[-\u{F0000}-\u{FFFFD}]+$/u.test(text.trim()) || /ionicons|material|feather/i.test(getComputedStyle(el).fontFamily);

  const contrast = [];
  const invisible = [];
  const bad = [];
  const raw = [];
  const offscreen = [];
  const clipped = [];
  const texts = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'OPTION'].includes(el.tagName)) continue;
    const text = n.textContent;
    if (!text.trim() || hidden(el)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter((r) => r.width > 1 && r.height > 1);
    if (!rects.length) continue;
    const icon = isIcon(el, text);
    const snippet = icon ? `(icon in ${desc(el)})` : text.trim().replace(/\s+/g, ' ').slice(0, 60);
    /* is any of it on screen horizontally? A text run left or right of the viewport is cut off */
    const cs = getComputedStyle(el);
    for (const rr of rects) {
      const c = clipRect(el, rr);
      /* the tab bar floats over the screen, which scrolls clear of it: not an overlap */
      if (c.w > 1 && c.h > 1 && !icon && !el.closest('[role=tablist]')) texts.push({ el, rect: c, text: snippet.slice(0, 40) });
      if ((rr.right > vw + 1 || rr.left < -1) && !scrollsX(el) && c.w > 0) offscreen.push({ where: desc(el), text: snippet, left: Math.round(rr.left), right: Math.round(rr.right) });
      else if (c.clippedBy && !icon && cs.textOverflow !== 'ellipsis' && !cs.webkitLineClamp?.match(/\d/) && (rr.right - c.right > 2 || rr.bottom - c.bottom > 2) && c.h > 0) clipped.push({ where: desc(el), text: snippet });
    }
    if (!icon) {
      if (/(^|\s)(undefined|null|NaN|\[object Object\])(\s|$|[.,:])/.test(text) || /\bNaN\b|\bundefined\b|\[object Object\]/.test(text)) bad.push({ where: desc(el), text: snippet });
      if (/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(text)) raw.push({ where: desc(el), text: snippet, what: 'an internal id' });
      else if (/^\s*[[{]\s*"/.test(text)) raw.push({ where: desc(el), text: snippet, what: 'JSON' });
      else if (/(^|\s)[a-z]+(_[a-z]+)+(\s|$|[.,])/.test(text) && !/@|https?:/.test(text)) raw.push({ where: desc(el), text: snippet, what: 'a code word' });
    }
    if (el.closest('[aria-disabled=true], [disabled]')) continue; /* WCAG exempts disabled controls */
    let fg = parse(cs.color);
    if (!fg) continue;
    fg = [fg[0], fg[1], fg[2], fg[3] * opacityOf(el)];
    const b = background(el);
    if (b.unknown) continue;
    const fgc = over(fg, b.color);
    const r = ratio(fgc, b.color);
    const size = parseFloat(cs.fontSize);
    const weight = Number(cs.fontWeight) || (/Bold|ExtraBold|SemiBold|_[678]00/.test(cs.fontFamily) ? 700 : 400);
    const large = size >= 24 || (weight >= 700 && size >= 18.66);
    const need = icon || large ? 3 : 4.5;
    if (r < need) {
      const k = desc(el) + '|' + hex(fgc) + '|' + hex(b.color) + '|' + snippet;
      if (seen.has(k)) continue;
      seen.add(k);
      const f = { where: desc(el), text: snippet, fg: hex(fgc), bg: hex(b.color), ratio: Math.round(r * 100) / 100, need, icon };
      if (r < 1.3) invisible.push(f);
      else contrast.push(f);
    }
  }
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea')) {
    if (hidden(el) || Number(getComputedStyle(el).opacity) < 0.1) continue;
    const v = el.value || el.placeholder;
    if (!v) continue;
    const cs = getComputedStyle(el);
    const fg = parse(el.value ? cs.color : getComputedStyle(el, '::placeholder').color);
    const b = background(el);
    if (!fg || b.unknown) continue;
    const r = ratio(over(fg, b.color), b.color);
    if (r < 4.5) contrast.push({ where: desc(el), text: `${el.value ? 'value' : 'placeholder'} "${v.slice(0, 30)}"`, fg: hex(over(fg, b.color)), bg: hex(b.color), ratio: Math.round(r * 100) / 100, need: 4.5 });
  }

  /* overlap: text runs that share pixels and are not nested */
  const overlaps = [];
  for (let i = 0; i < texts.length && overlaps.length < 10; i++) {
    for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i], b = texts[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left);
      const h = Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top);
      if (w > 3 && h > 3 && w * h > 0.25 * Math.min(a.rect.w * a.rect.h, b.rect.w * b.rect.h)) {
        overlaps.push({ a: desc(a.el), at: a.text, b: desc(b.el), bt: b.text });
        if (overlaps.length >= 10) break;
      }
    }
  }

  /* touch targets: everything a finger presses */
  const small = [];
  for (const el of document.querySelectorAll('[role=button], [role=link], [role=tab], [role=radio], [role=checkbox], [role=switch], a[href], button, input:not([type=hidden]), textarea')) {
    if (hidden(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    /* an input under a custom control (the code boxes) is pressed through its parent */
    if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && Number(getComputedStyle(el).opacity) < 0.1) continue;
    if (r.width < 43.5 || r.height < 43.5) {
      /* a control inside a bigger control is reached through the bigger one */
      const outer = el.parentElement && el.parentElement.closest('[role=button], [role=link], a[href]');
      if (outer && !hidden(outer)) { const o = outer.getBoundingClientRect(); if (o.width >= 44 && o.height >= 44) continue; }
      small.push({ where: desc(el), text: (el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 40), w: Math.round(r.width), h: Math.round(r.height) });
    }
  }

  const images = [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && !hidden(i)).map((i) => ({ where: desc(i), src: (i.currentSrc || i.src).slice(0, 120) }));
  const visibleText = texts.map((t) => t.text).join(' ').replace(/\s+/g, ' ').trim();
  /* a spinner is a progress bar with no value and a maximum of 1 (React Native Web); a step bar at step 0 has its own maximum */
  const loading = [...document.querySelectorAll('[aria-label=Loading], [role=progressbar][aria-busy=true]')].some((e) => !hidden(e)) ||
    [...document.querySelectorAll('[role=progressbar]')].some((e) => !hidden(e) && !e.hasAttribute('aria-valuenow') && [null, '1'].includes(e.getAttribute('aria-valuemax')) && e.getBoundingClientRect().width > 0);
  /* photos (React Native Web draws them as background images) and PDF frames are content too */
  const media = [...document.querySelectorAll('img, iframe, [style*="background-image"]')].filter((e) => !hidden(e) && e.getBoundingClientRect().width > 80).length;
  const html = document.documentElement;
  return {
    contrast, invisible, overlaps, small, images, bad, raw: raw.slice(0, 8), offscreen: offscreen.slice(0, 6), clipped: clipped.slice(0, 6),
    overflow: html.scrollWidth > vw + 1 ? html.scrollWidth : 0,
    textLength: visibleText.length, text: visibleText.slice(0, 200), loading, media,
    width: vw, height: vh,
  };
}

/* ---------- driver ---------- */
/* The newest code the console SMS adapter printed after `offset`, to the number ending in `tail`. */
function smsCodeAfter(offset, tail) {
  if (!API_LOG) return null;
  const log = fs.readFileSync(API_LOG, 'utf8').slice(offset);
  const all = [...log.matchAll(/\[sms\] to (\+?\d+): .*?\b(\d{6})\b/g)].filter((m) => !tail || m[1].endsWith(tail));
  return all.length ? all[all.length - 1][2] : null;
}

async function settle(page, ms = SETTLE_MS) {
  const until = Date.now() + ms;
  let quiet = 0;
  await page.waitForTimeout(150);
  while (Date.now() < until) {
    const busy = await page.evaluate(() => {
      const vis = (e) => { for (let x = e; x && x.nodeType === 1; x = x.parentElement) { const cs = getComputedStyle(x); if (cs.display === 'none' || cs.visibility === 'hidden') return false; } return e.getBoundingClientRect().width > 0; };
      const loading = [...document.querySelectorAll('[aria-label=Loading], [aria-label="Connecting to Tenmina…"]')].some(vis) ||
        [...document.querySelectorAll('[role=progressbar]')].some((e) => vis(e) && !e.hasAttribute('aria-valuenow') && [null, '1'].includes(e.getAttribute('aria-valuemax')));
      /* the app's own start screen ("Connecting to Tenmina…") comes before every screen after a reload */
      const text = (document.body.innerText || '').trim();
      return loading || text.length < 3 || /Connecting to Tenmina/.test(text) || window.__auditInflight > 0;
    }).catch(() => true);
    /* two quiet checks in a row, so a screen between two states is not taken as settled */
    quiet = busy ? 0 : quiet + 1;
    if (quiet >= 2) break;
    await page.waitForTimeout(200);
  }
  await page.waitForTimeout(200);
}

async function stillLoading(page) {
  return page.evaluate(() => [...document.querySelectorAll('[aria-label=Loading]')].some((e) => e.getBoundingClientRect().width > 0)).catch(() => false);
}

async function signIn(page, base, role, log) {
  await page.goto(base + (role.app === 'client' ? '/sign-in' : '/welcome'), { waitUntil: 'domcontentloaded' });
  await settle(page);
  await page.getByLabel('Email or mobile number').fill(role.email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  const offset = API_LOG ? fs.statSync(API_LOG).size : 0;
  await page.getByRole('button', { name: /^\W*Sign in$/ }).click();
  await settle(page, 6000);
  const codeBox = page.getByRole('textbox', { name: /^Code from/ });
  if (await codeBox.count()) {
    let code;
    if (role.sms) {
      const tail = ((await page.innerText('body')).match(/•+ ?(\d{2,4})\b/) || [])[1];
      for (let i = 0; i < 20 && !code; i++) { code = smsCodeAfter(offset, tail); if (!code) await page.waitForTimeout(250); }
      if (!code) throw new Error('no SMS code found in the API log');
      log.push(`signed in with the SMS code from the API log`);
    } else code = totp(MFA_SECRET);
    await codeBox.first().fill(code);
    await page.getByRole('button', { name: /Confirm and sign in$/ }).click();
    await settle(page, 8000);
  }
  /* the client app offers Face ID once, then notifications; the field app registers the phone */
  for (let i = 0; i < 20; i++) {
    const url = page.url();
    if (role.app === 'client' && !/sign-in|face-id|turn-on-notifications/.test(url)) break;
    if (role.app === 'field' && !/welcome/.test(url)) break;
    const notNow = page.getByRole('button', { name: /^(Not now|Skip|Later)/ });
    if (await notNow.count()) await notNow.first().click().catch(() => undefined);
    await page.waitForTimeout(500);
  }
  const token = await page.evaluate(() => localStorage.getItem('tenmina.tokens'));
  if (!token) throw new Error(`sign-in did not finish (at ${page.url()}): ${(await page.innerText('body')).slice(0, 200)}`);
}

async function audit(page, log, shots, name) {
  const out = {};
  for (const m of MODES) {
    await page.setViewportSize({ width: m.width, height: m.height });
    await page.emulateMedia({ colorScheme: m.scheme, reducedMotion: 'reduce' });
    await page.waitForTimeout(150);
    out[m.name] = await page.evaluate(viewChecks);
    if (shots && (m.width === 390)) {
      fs.mkdirSync(shots, { recursive: true });
      await page.screenshot({ path: path.join(shots, `${name.replace(/[^a-z0-9]+/gi, '_')}_${m.scheme}.png`) }).catch(() => undefined);
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });
  out.console = log.splice(0);
  return out;
}

/* The buttons, links, tabs and rows on screen, as {label, n} where n tells same-named ones apart. */
async function pressables(page) {
  return page.evaluate((never) => {
    const re = new RegExp(never, 'i');
    const vis = (e) => { for (let x = e; x && x.nodeType === 1; x = x.parentElement) { const cs = getComputedStyle(x); if (cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') return false; } const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const counts = {};
    const out = [];
    for (const el of document.querySelectorAll('[role=button], [role=link], [role=tab], a[href]')) {
      if (!vis(el) || el.getAttribute('aria-disabled') === 'true') continue;
      const label = (el.getAttribute('aria-label') || el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80);
      if (!label || re.test(label)) continue;
      counts[label] = (counts[label] || 0) + 1;
      out.push({ label, n: counts[label] - 1, role: el.getAttribute('role') || 'link' });
    }
    return out;
  }, NEVER_PRESS.source);
}

async function press(page, target) {
  return page.evaluate(({ label, n }) => {
    const vis = (e) => { for (let x = e; x && x.nodeType === 1; x = x.parentElement) { const cs = getComputedStyle(x); if (cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') return false; } const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const all = [...document.querySelectorAll('[role=button], [role=link], [role=tab], a[href]')].filter((el) => vis(el) && (el.getAttribute('aria-label') || el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80) === label);
    const el = all[n];
    if (!el) return false;
    el.scrollIntoView({ block: 'center' });
    el.click();
    return true;
  }, target);
}

/* API links to app screens, as the client app maps them (apps/client/src/lib.ts, ROUTES), for the dynamic routes only. */
const CLIENT_LINKS = [
  [/^\/cases\/([^/?]+)(?:\/document-requests\/[^/?]+)?$/, '/case/'],
  [/^\/reports\/([^/?]+)$/, '/report/'],
  [/^\/(?:escrows|commitments)\/([^/?]+)$/, '/escrow/'],
  [/^\/release-instructions\/([^/?]+)$/, '/release/'],
  [/^\/invoices\/([^/?]+)$/, '/invoice/'],
  [/^\/fee-payments\/([^/?]+)$/, '/fee-payment/'],
  [/^\/projects\/([^/?]+)$/, '/project/'],
  [/^\/properties\/([^/?]+)$/, '/managed/'],
  [/^\/repairs\/([^/?]+)$/, '/repair/'],
  [/^\/care\/plans\/([^/?]+)$/, '/care-plan/'],
  [/^\/care\/visits\/([^/?]+)$/, '/care-visit/'],
  [/^\/care\/concerns\/([^/?]+)$/, '/concern/'],
  [/^\/errands\/([^/?]+)$/, '/errand/'],
  [/^\/events\/([^/?]+)(?:\/receipts)?$/, '/event/'],
  [/^\/insurance\/policies\/([^/?]+)$/, '/policy/'],
  [/^\/insurance\/premiums\/([^/?]+)$/, '/premium/'],
  [/^\/disputes\/([^/?]+)$/, '/dispute/'],
  [/^\/(?:escrows\/[^/?]+\/)?payee-changes\/([^/?]+)$/, '/payee-change/'],
  [/^\/listings\/([^/?]+)$/, '/listing/'],
  [/^\/orders\/([^/?]+)(?:\/pay)?$/, '/pay-fee/'],
  [/^\/(?:family\/)?members\/([^/?]+)$/, '/member/'],
];

/* App URLs for the links the API gives this person: home rows and notifications (client), payables and errands (field). */
async function deepLinks(app, headers) {
  const get = async (p) => {
    try {
      const r = await fetch(API + p, { headers: { ...headers, accept: 'application/json' } });
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  };
  const out = [];
  if (app === 'client') {
    const links = [];
    (function walk(v) {
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) { if (k === 'link' && typeof x === 'string') links.push(x); else walk(x); }
    })([await get('/v1/home'), await get('/v1/me/notifications?page_size=100')]);
    for (const l of links) {
      const p = l.split('?')[0];
      for (const [re, to] of CLIENT_LINKS) { const m = p.match(re); if (m) { out.push(to + m[1]); break; } }
    }
  } else {
    const items = (j) => (Array.isArray(j) ? j : j?.items ?? j?.results ?? []);
    for (const p of items(await get('/v1/me/pro/payables'))) out.push(`/pay/${p.id}`);
    for (const e of items(await get('/v1/mobile/errands'))) out.push(`/errand/${e.id}`);
    /* jobs open from the synced list on the phone; an errand's steps open the errand screen instead */
    for (const j of items(await get('/v1/mobile/inbox'))) if (j.subject_type && j.subject_type !== 'errand_step') out.push(`/job/${j.subject_type}/${j.subject_id}`);
  }
  return [...new Set(out)];
}

async function runRole(browser, role, allRoutes, results, shots) {
  const base = `http://localhost:${APPS[role.app].port}`;
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, reducedMotion: 'reduce', isMobile: false, hasTouch: false });
  await context.addInitScript(() => {
    /* count API calls in flight, so settle() waits for them */
    window.__auditInflight = 0;
    const f = window.fetch;
    window.fetch = (...a) => { window.__auditInflight++; return f(...a).finally(() => { window.__auditInflight--; }); };
  });
  const page = await context.newPage();
  const log = [];
  let exploring = false;
  const blocked = [];
  page.on('console', (msg) => { if (msg.type() === 'error' && !/Failed to load resource/.test(msg.text())) log.push('console: ' + msg.text().slice(0, 220)); });
  page.on('pageerror', (err) => log.push('page error: ' + String(err.message || err).slice(0, 220)));
  page.on('response', (res) => {
    const u = res.url();
    if (u.startsWith(API) && res.status() >= 400 && res.status() !== 418 && !(role.email === null && res.status() === 401)) log.push(`api ${res.status()}: ${res.request().method()} ${new URL(u).pathname}`);
  });
  /* --trace: print every API call with its timing, to see why a screen is slow */
  if (args.trace) {
    const t0 = Date.now();
    page.on('request', (req) => { if (req.url().startsWith(API)) console.log(`${((Date.now() - t0) / 1000).toFixed(1)} > ${req.method()} ${new URL(req.url()).pathname}`); });
    page.on('requestfinished', async (req) => { if (req.url().startsWith(API)) { const r = await req.response(); console.log(`${((Date.now() - t0) / 1000).toFixed(1)} < ${r?.status()} ${req.method()} ${new URL(req.url()).pathname}`); } });
    page.on('requestfailed', (req) => { if (req.url().startsWith(API)) console.log(`${((Date.now() - t0) / 1000).toFixed(1)} x ${req.method()} ${new URL(req.url()).pathname} ${req.failure()?.errorText}`); });
    page.on('framenavigated', (f) => { if (f === page.mainFrame()) console.log(`${((Date.now() - t0) / 1000).toFixed(1)} == ${f.url()}`); });
  }
  /* API calls in flight, to name what a stuck screen waits for */
  const inflight = new Map();
  page.on('request', (req) => { if (req.url().startsWith(API)) inflight.set(req, Date.now()); });
  page.on('requestfinished', (req) => inflight.delete(req));
  page.on('requestfailed', (req) => inflight.delete(req));
  page.on('requestfailed', (req) => { if (req.url().startsWith(API) && !/ERR_FAILED|aborted/i.test(req.failure()?.errorText || '')) log.push(`api failed: ${req.method()} ${new URL(req.url()).pathname} ${req.failure()?.errorText}`); });
  /* While exploring, nothing may change on the server: mutations get a 418 the crawler ignores. */
  await page.route(API + '/**', (route) => {
    const req = route.request();
    if (exploring && !['GET', 'HEAD', 'OPTIONS'].includes(req.method()) && !req.url().endsWith('/v1/auth/refresh')) {
      blocked.push(`${req.method()} ${new URL(req.url()).pathname}`);
      return route.fulfill({ status: 418, contentType: 'application/problem+json', headers: { 'Access-Control-Allow-Origin': base, 'Access-Control-Allow-Credentials': 'true' }, body: JSON.stringify({ type: 'about:blank', title: 'Blocked by the audit', status: 418, detail: 'The audit does not change anything.', code: 'audit-blocked' }) });
    }
    return route.continue();
  });
  if (role.email) await signIn(page, base, role, log);
  log.splice(0);
  exploring = true;

  const routeOf = (u) => {
    const p = new URL(u).pathname;
    return allRoutes.find((r) => !r.dynamic && r.re.test(p)) || allRoutes.find((r) => r.re.test(p));
  };
  const startUrls = role.email ? allRoutes.filter((r) => !r.dynamic && !PUBLIC[role.app].includes(r.pattern) && !/^\/(face-id|turn-on-notifications|capture)$/.test(r.pattern)) .map((r) => r.pattern) : PUBLIC[role.app];
  const queue = startUrls.map((u) => ({ url: base + u, from: '(route)' }));
  const visited = new Set();
  const perPattern = {};
  const pressedOnPattern = new Set();
  const labelLeadsTo = new Map();
  let views = 0;
  /* the last Authorization and Tenmina-App headers the app sent, to ask the API for deep links */
  let apiHeaders = null;
  page.on('request', (req) => {
    if (!req.url().startsWith(API)) return;
    const h = req.headers();
    if (h.authorization) apiHeaders = { authorization: h.authorization, ...(h['tenmina-app'] ? { 'tenmina-app': h['tenmina-app'] } : {}) };
  });
  const drain = async () => {
  while (queue.length && views < MAX_VIEWS) {
    const { url, from } = queue.shift();
    const rt = routeOf(url);
    const key = rt ? rt.pattern : new URL(url).pathname;
    const vkey = new URL(url).pathname + new URL(url).search;
    if (visited.has(vkey)) continue;
    if (rt?.dynamic && (perPattern[key] || 0) >= 2) continue;
    visited.add(vkey);
    perPattern[key] = (perPattern[key] || 0) + 1;
    inflight.clear(); /* calls of the page before are cancelled by the reload */
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    } catch (e) {
      results.push({ app: role.app, role: role.key, url, key, error: String(e.message).slice(0, 200) });
      continue;
    }
    const t0 = Date.now();
    await settle(page);
    /* a screen still loading gets a second chance, so a busy development server is not taken for a stuck screen */
    if (await stillLoading(page)) await settle(page, SETTLE_MS * 2);
    const loadMs = Date.now() - t0;
    const waitingFor = [...inflight.entries()].map(([req, at]) => `${req.method()} ${new URL(req.url()).pathname} (${Math.round((Date.now() - at) / 1000)} s)`);
    views++;
    const finalUrl = page.url();
    const finalRoute = routeOf(finalUrl);
    const entry = { app: role.app, role: role.key, url: url.replace(base, ''), finalUrl: finalUrl.replace(base, ''), from: from.replace(base, ''), key: finalRoute?.pattern || key, loadMs, waitingFor, checks: await audit(page, log, shots, `${role.app}_${role.key}_${finalRoute?.pattern || key}`), views: {} };
    results.push(entry);
    process.stdout.write(`${role.app}/${role.key} ${entry.finalUrl}\n`);
    if (finalUrl !== url && finalRoute && !finalRoute.dynamic) visited.add(new URL(finalUrl).pathname);
    /* press what is on screen: new screens join the queue, in-place changes (sheets, tabs, open rows) are audited here */
    const baseText = await page.evaluate(() => document.body.innerText).catch(() => '');
    const items = (await pressables(page)).slice(0, 80);
    let clicks = 0;
    for (const it of items) {
      if (clicks >= MAX_CLICKS || views >= MAX_VIEWS) break;
      const pk = `${entry.key}|${it.label}|${it.n}`;
      if (pressedOnPattern.has(pk)) continue;
      if (it.n > 2) continue;
      const known = labelLeadsTo.get(it.label);
      if (known && visited.has(known)) continue;
      pressedOnPattern.add(pk);
      if (page.url() !== finalUrl) { await page.goto(finalUrl, { waitUntil: 'domcontentloaded' }).catch(() => undefined); await settle(page); }
      const blockedBefore = blocked.length;
      const ok = await press(page, it).catch(() => false);
      if (!ok) continue;
      clicks++;
      await settle(page, 4000);
      const mutated = blocked.length > blockedBefore;
      const now = page.url();
      if (now !== finalUrl) {
        const r = routeOf(now);
        const p = new URL(now).pathname + new URL(now).search;
        if (r && !r.dynamic) labelLeadsTo.set(it.label, p);
        if (r && !visited.has(p) && !(r.dynamic && (perPattern[r.pattern] || 0) >= 2)) queue.unshift({ url: now, from: `${entry.finalUrl} ("${it.label}")` });
        else if (!r) entry.dead = [...(entry.dead || []), `"${it.label}" opened ${new URL(now).pathname}, which is not a screen of the app`];
        await page.goBack().catch(() => undefined);
        await settle(page, 3000);
        continue;
      }
      const text = await page.evaluate(() => document.body.innerText).catch(() => '');
      if (text !== baseText) {
        /* a press that only tried to change something shows the audit's own refusal: nothing new to check */
        if (!mutated && Object.keys(entry.views).length < 8) entry.views[it.label] = await audit(page, log, shots, `${role.app}_${role.key}_${entry.key}_after_${it.label}`);
        else log.splice(0);
        await page.goto(finalUrl, { waitUntil: 'domcontentloaded' }).catch(() => undefined);
        await settle(page);
      }
    }
  }
  };
  await drain();
  /* Screens a person reaches only from a row far down a long list (a care concern, a payee change, one payable):
     open them straight from the links the API gives this person, as a notification or a home row would. */
  if (role.email && apiHeaders && views < MAX_VIEWS) {
    const reachedNow = new Set(results.filter((r) => r.role === role.key && r.app === role.app && r.checks).map((r) => r.key));
    for (const u of await deepLinks(role.app, apiHeaders)) {
      const r = routeOf(base + u);
      if (r && r.dynamic && !reachedNow.has(r.pattern) && !visited.has(u) && (perPattern[r.pattern] || 0) < 2) {
        queue.push({ url: base + u, from: '(a link the API gives this person)' });
        reachedNow.add(r.pattern);
      }
    }
    await drain();
  }
  const reached = new Set(results.filter((r) => r.role === role.key && r.app === role.app && r.checks).map((r) => r.key));
  results.push({ app: role.app, role: role.key, coverage: { views, reached: [...reached], blocked: [...new Set(blocked)] } });
  await context.close();
}

/* ---------- report ---------- */
const KINDS = ['invisible-text', 'contrast', 'overflow', 'cut-off', 'overlap', 'touch-target', 'empty', 'still-loading', 'broken-image', 'bad-text', 'raw-data', 'dead-link', 'navigation', 'console'];
const BLOCKING = new Set(KINDS.filter((k) => k !== 'console'));

function summarise(results) {
  const findings = [];
  const add = (f) => findings.push(f);
  for (const r of results) {
    if (r.coverage) continue;
    const who = `${r.app}/${r.role}`;
    if (r.error) { add({ kind: 'navigation', page: r.key, role: who, mode: '-', detail: r.error }); continue; }
    for (const [suffix, checks] of [['', r.checks], ...Object.entries(r.views).map(([t, c]) => [` after "${t}"`, c])]) {
      const page = r.key + suffix;
      for (const m of MODES) {
        const c = checks[m.name];
        if (!c) continue;
        for (const x of c.invisible) add({ kind: 'invisible-text', page, role: who, mode: m.name, detail: `${x.ratio}:1 ${x.fg} on ${x.bg} "${x.text}" at ${x.where}`, sig: `${x.where}|${x.text}` });
        for (const x of c.contrast) add({ kind: 'contrast', page, role: who, mode: m.name, detail: `${x.ratio}:1 (needs ${x.need}) ${x.fg} on ${x.bg} "${x.text}" at ${x.where}`, sig: `${x.where}|${x.text}|${x.fg}|${x.bg}` });
        if (c.overflow) add({ kind: 'overflow', page, role: who, mode: m.name, detail: `page ${c.overflow}px wide at ${c.width}px`, sig: 'overflow' });
        for (const o of c.offscreen) add({ kind: 'overflow', page, role: who, mode: m.name, detail: `"${o.text}" runs off the screen (${o.left} to ${o.right} at ${c.width}px) at ${o.where}`, sig: o.where + o.text });
        for (const o of c.clipped) add({ kind: 'cut-off', page, role: who, mode: m.name, detail: `"${o.text}" is cut off by its container at ${o.where}`, sig: o.where + o.text });
        for (const o of c.overlaps) add({ kind: 'overlap', page, role: who, mode: m.name, detail: `"${o.at}" (${o.a}) overlaps "${o.bt}" (${o.b})`, sig: o.a + o.at + o.b + o.bt });
        for (const s of c.small) add({ kind: 'touch-target', page, role: who, mode: m.name, detail: `${s.w}x${s.h} "${s.text}" at ${s.where}`, sig: s.where + s.text });
        for (const i of c.images) add({ kind: 'broken-image', page, role: who, mode: m.name, detail: `${i.src} at ${i.where}`, sig: i.src });
        for (const b of c.bad) add({ kind: 'bad-text', page, role: who, mode: m.name, detail: `"${b.text}" at ${b.where}`, sig: b.where + b.text });
        for (const b of c.raw) add({ kind: 'raw-data', page, role: who, mode: m.name, detail: `${b.what}: "${b.text}" at ${b.where}`, sig: b.where + b.text });
      }
      const c = checks[MODES[0].name];
      if (c.loading) add({ kind: 'still-loading', page, role: who, mode: 'all', detail: `still loading after ${(SETTLE_MS * 3) / 1000} s${!suffix && r.waitingFor?.length ? `; waiting for ${r.waitingFor.join(', ')}` : '; no API call in flight'}`, sig: 'loading' });
      else if (!suffix && r.loadMs > SETTLE_MS) add({ kind: 'console', page, role: who, mode: 'all', detail: `slow: took ${Math.round(r.loadMs / 1000)} s to load`, sig: 'slow' });
      else if (c.textLength < 30 && !c.media) add({ kind: 'empty', page, role: who, mode: 'all', detail: `the screen shows only "${c.text}"`, sig: 'empty' });
    }
    for (const d of r.dead || []) add({ kind: 'dead-link', page: r.key, role: who, mode: 'all', detail: d, sig: d });
    for (const l of [...new Set([...(r.checks.console || []), ...Object.values(r.views).flatMap((v) => v.console || [])])]) add({ kind: 'console', page: r.key, role: who, mode: 'all', detail: l, sig: l });
  }
  const merged = new Map();
  for (const f of findings) {
    const k = [f.kind, f.page, f.role, f.sig || f.detail].join('|');
    if (!merged.has(k)) merged.set(k, { ...f, modes: new Set() });
    merged.get(k).modes.add(f.mode);
  }
  return [...merged.values()].map((f) => ({ ...f, modes: [...f.modes].join(', ') }));
}

function report(results, findings, started) {
  const pages = results.filter((r) => !r.coverage && !r.error);
  const views = pages.reduce((n, r) => n + 1 + Object.keys(r.views).length, 0);
  const lines = [];
  lines.push('# Phone apps UI audit: raw results', '');
  lines.push(`Run ${started.toISOString().slice(0, 16).replace('T', ' ')} UTC by \`scripts/ui-audit/apps.js\` on the web export of each app, against the seeded development data (\`seed_dev\`).`);
  lines.push(`Modes: ${MODES.map((m) => `${m.width}x${m.height} ${m.scheme}`).join(', ')}. Contrast 4.5:1, or 3:1 for text 24 px and up, bold 18.66 px and up, and icons.`, '');
  lines.push(`Screens visited: ${pages.length} (${views} views including sheets and in-place changes), each checked in ${MODES.length} modes.`, '');
  lines.push('| Check | Findings |', '|---|---|');
  for (const k of KINDS) lines.push(`| ${k}${BLOCKING.has(k) ? '' : ' (for information)'} | ${findings.filter((f) => f.kind === k).length} |`);
  lines.push('');
  for (const k of KINDS) {
    const fs_ = findings.filter((f) => f.kind === k);
    if (!fs_.length) continue;
    lines.push(`## ${k}`, '');
    for (const f of fs_.slice(0, 400)) lines.push(`- \`${f.page}\` as ${f.role} [${f.modes}]: ${f.detail.replace(/\|/g, '\\|')}`);
    if (fs_.length > 400) lines.push(`- … and ${fs_.length - 400} more`);
    lines.push('');
  }
  lines.push('## Coverage', '');
  const all = { client: routes('client'), field: routes('field') };
  for (const r of results.filter((x) => x.coverage)) {
    const mine = all[r.app].map((x) => x.pattern);
    const missing = r.role === 'public' ? [] : mine.filter((p) => !r.coverage.reached.includes(p) && !PUBLIC[r.app].includes(p));
    lines.push(`- ${r.app}/${r.role}: ${r.coverage.views} screens.${missing.length ? ` Not reached: ${missing.map((p) => `\`${p}\``).join(', ')}.` : ''}`);
  }
  lines.push('');
  return lines.join('\n');
}

(async () => {
  const started = new Date();
  const only = args.app;
  const roleKeys = args.roles ? args.roles.split(',') : null;
  const servers = [];
  for (const [name, a] of Object.entries(APPS)) {
    if (only && only !== name) continue;
    if (!a.dist || !fs.existsSync(path.join(a.dist, 'index.html'))) throw new Error(`--${name}-dist must point at the app's web export (npx expo export --platform web)`);
    servers.push(await serve(path.resolve(a.dist), a.port));
  }
  const all = { client: routes('client'), field: routes('field') };
  const browser = await chromium.launch();
  const results = [];
  const todo = ROLES.filter((role) => (!only || role.app === only) && (!roleKeys || roleKeys.includes(role.key)));
  /* a few people at once, each in their own browser context */
  const workers = Array.from({ length: Number(args.parallel || 3) }, async () => {
    for (let role = todo.shift(); role; role = todo.shift()) {
      try {
        await runRole(browser, role, all[role.app], results, args.shots);
      } catch (e) {
        results.push({ app: role.app, role: role.key, url: '(sign in)', key: '(sign in)', error: String(e.message).slice(0, 300) });
      }
    }
  });
  await Promise.all(workers);
  results.sort((a, b) => ROLES.findIndex((r) => r.app === a.app && r.key === a.role) - ROLES.findIndex((r) => r.app === b.app && r.key === b.role));
  await browser.close();
  servers.forEach((s) => s.close());
  const findings = summarise(results);
  const out = args.out || path.join(ROOT, 'scripts', 'ui-audit', 'apps-results.md');
  fs.writeFileSync(out, report(results, findings, started));
  if (args.json) fs.writeFileSync(args.json, JSON.stringify({ results, findings }, null, 1));
  const blocking = findings.filter((f) => BLOCKING.has(f.kind));
  console.log(`\n${findings.length} findings (${blocking.length} blocking). Report: ${path.relative(process.cwd(), out)}`);
  process.exitCode = blocking.length ? 1 : 0;
})();
