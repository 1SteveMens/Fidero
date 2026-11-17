#!/usr/bin/env node
/*
 * UI audit for the two web apps (portal and back office).
 *
 * Signs in as each seeded role, visits every route found under the apps'
 * Next.js `src/app` folders, follows links (and clickable table rows) to one
 * page of each detail route, and on every page, at 390x844 and 1280x800, in
 * light and dark colour scheme, checks:
 *   - contrast of every visible text node against its effective background
 *     (4.5:1, or 3:1 for text 24 px and up or bold 18.66 px and up)
 *   - horizontal overflow (page wider than the viewport)
 *   - overlapping text
 *   - empty pages with no empty state, and pages still loading after 10 s
 *   - broken images, and "undefined" / "null" / "NaN" shown as text
 *   - console errors, page errors and failed API calls
 *
 * Usage (servers running, API seeded with `seed_dev`):
 *   node scripts/ui-audit/audit.js \
 *     --portal http://localhost:3114 --backoffice http://localhost:3115 \
 *     [--app portal|backoffice] [--roles client,cm] [--max 150] \
 *     [--out scripts/ui-audit/report.md] [--json path.json] [--api-log path/to/runserver.log]
 *   --api-log: the API's log file, where the development SMS adapter writes sign-in codes for clients.
 *
 * Playwright comes from the machine (`require('playwright')`).
 */
'use strict';
const fs = require('fs');
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
const BASE = { portal: args.portal || 'http://localhost:3114', backoffice: args.backoffice || 'http://localhost:3115' };
const PASSWORD = 'tenmina-dev-123';
const MFA_SECRET = 'JBSWY3DPEHPK3PXP';
const MAX_PAGES = Number(args.max || 150);
const SETTLE_MS = Number(args.settle || 10000);
const MODES = [
  { name: 'phone-light', width: 390, height: 844, scheme: 'light' },
  { name: 'phone-dark', width: 390, height: 844, scheme: 'dark' },
  { name: 'desktop-light', width: 1280, height: 800, scheme: 'light' },
  { name: 'desktop-dark', width: 1280, height: 800, scheme: 'dark' },
];

/* Roles: who signs in to which app, and where they start. Seeded in api/accounts/seed.py. */
const ROLES = [
  { app: 'portal', key: 'public', email: null, sections: ['(public)', 'login', 'register'] },
  { app: 'portal', key: 'client', email: 'ama@example.com', sections: ['(app)', '(public)'] },
  { app: 'portal', key: 'lawyer', email: 'lawyer@example.com', sections: ['(roles)/work'], mfa: true },
  { app: 'portal', key: 'surveyor', email: 'surveyor@example.com', sections: ['(roles)/work'], mfa: true },
  { app: 'portal', key: 'inspector', email: 'inspector@example.com', sections: ['(roles)/work'], mfa: true },
  { app: 'portal', key: 'carer', email: 'carer@example.com', sections: ['(roles)/work'], mfa: true },
  { app: 'portal', key: 'seller', email: 'seller@example.com', sections: ['(roles)/seller'] },
  { app: 'portal', key: 'contractor', email: 'builder@example.com', sections: ['(roles)/contractor'] },
  { app: 'portal', key: 'family', email: 'auntie@example.com', sections: ['(roles)/family-member'] },
  { app: 'portal', key: 'institution', email: 'bursar@example.com', sections: ['(roles)/institution'] },
  { app: 'portal', key: 'partner', email: 'partner@example.com', sections: ['(roles)/partner'] },
  { app: 'portal', key: 'insurer', email: 'insurer@example.com', sections: ['(roles)/insurer'], mfa: true },
  { app: 'portal', key: 'tenant', email: 'tenant@example.com', sections: ['(roles)/tenant'] },
  { app: 'portal', key: 'authority', email: 'stool@example.com', sections: ['(roles)/authority'] },
  { app: 'backoffice', key: 'public', email: null, sections: ['login'] },
  { app: 'backoffice', key: 'admin', email: 'admin@tenmina.test', sections: ['(work)'], mfa: true },
  { app: 'backoffice', key: 'cm', email: 'cm@tenmina.test', sections: ['(work)'], mfa: true },
  { app: 'backoffice', key: 'reviewer', email: 'rv1@tenmina.test', sections: ['(work)'], mfa: true },
  { app: 'backoffice', key: 'dpo', email: 'admin3@tenmina.test', sections: ['(work)'], mfa: true },
];

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

/* Routes from the Next.js app folder: [{file, section, pattern, re, dynamic}] */
function routes(app) {
  const dir = path.join(ROOT, 'apps', app, 'src', 'app');
  const out = [];
  (function walk(d, rel) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.isDirectory()) walk(path.join(d, e.name), [...rel, e.name]);
      else if (e.name === 'page.tsx') {
        const url = '/' + rel.filter((s) => !/^\(.*\)$/.test(s)).join('/');
        const re = new RegExp('^' + url.replace(/\[[^\]]+\]/g, '[^/]+') + '/?$');
        out.push({ section: rel.join('/'), pattern: url, re, dynamic: url.includes('[') });
      }
    }
  })(dir, []);
  return out;
}

const ID_LIKE = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{27}|\d+|[A-Za-z0-9_-]{20,}|[A-Z]{2,4}-[A-Z]{2}-\d{4}-\d+)$/;
function keyOf(u) {
  const url = new URL(u);
  const p = url.pathname.split('/').map((s) => (ID_LIKE.test(s) ? ':id' : s)).join('/');
  const tab = url.searchParams.get('tab');
  return tab ? `${p}?tab=${tab}` : p;
}

/* ---------- in-page checks (run inside the browser) ---------- */
function pageChecks() {
  const parse = (c) => {
    const m = c && c.match(/rgba?\(([^)]+)\)/);
    if (!m) {
      const m2 = c && c.match(/color\(srgb ([^)]+)\)/);
      if (!m2) return null;
      const p = m2[1].replace('/', ' ').split(/\s+/).filter(Boolean).map(Number);
      return [p[0] * 255, p[1] * 255, p[2] * 255, p[3] === undefined ? 1 : p[3]];
    }
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
  const desc = (el) => {
    const parts = [];
    for (let e = el, i = 0; e && e.nodeType === 1 && i < 4 && e !== document.body; e = e.parentElement, i++) {
      const cls = [...e.classList].filter((c) => !/^(jsx|css)-/.test(c)).slice(0, 2).join('.');
      parts.unshift(e.tagName.toLowerCase() + (cls ? '.' + cls : ''));
    }
    return parts.join(' > ');
  };
  const canvas = (() => {
    for (const e of [document.body, document.documentElement]) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) return [...c.slice(0, 3), 1];
    }
    return matchMedia('(prefers-color-scheme: dark)').matches ? [18, 18, 18, 1] : [255, 255, 255, 1];
  })();
  /* Effective background: composite non-transparent backgrounds up the tree; images and gradients are unknown. */
  const bgCache = new Map();
  const background = (el) => {
    const layers = [];
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (bgCache.has(e) && layers.length === 0) return bgCache.get(e);
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return { unknown: cs.backgroundImage.slice(0, 40) };
      if (e.tagName === 'IMG' || e.tagName === 'VIDEO' || e.tagName === 'CANVAS') return { unknown: e.tagName };
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) {
        layers.push(c);
        if (c[3] >= 1) break;
      }
    }
    let bg = canvas;
    for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
    const r = { color: bg };
    if (layers.length && layers[0] === layers[layers.length - 1]) bgCache.set(el, r);
    return r;
  };
  const opacityOf = (el) => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; };
  const vw = document.documentElement.clientWidth;
  /* Visible rectangle after clipping by overflow ancestors. */
  const clipRect = (el, r) => {
    let { left, top, right, bottom } = r;
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible' || cs.clipPath !== 'none') {
        if (cs.clipPath !== 'none') continue;
        const b = e.getBoundingClientRect();
        left = Math.max(left, b.left); top = Math.max(top, b.top); right = Math.min(right, b.right); bottom = Math.min(bottom, b.bottom);
      }
    }
    return { left, top, right, bottom, w: right - left, h: bottom - top };
  };
  const hidden = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      /* the body of a closed <details> is not rendered (only its summary is) */
      if (e.parentElement && e.parentElement.tagName === 'DETAILS' && !e.parentElement.open && e.tagName !== 'SUMMARY') return true;
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.contentVisibility === 'hidden') return true;
      if (cs.clip === 'rect(0px, 0px, 0px, 0px)' || (cs.position === 'absolute' && e.offsetWidth <= 1 && e.offsetHeight <= 1 && cs.overflow === 'hidden')) return true;
    }
    return false;
  };
  const fixedAncestor = (el) => { for (let e = el; e && e.nodeType === 1; e = e.parentElement) { const p = getComputedStyle(e).position; if (p === 'fixed' || p === 'sticky') return e; } return null; };

  const contrast = [];
  const texts = [];
  const bad = [];
  const unknownBg = [];
  const seen = new Set();
  const consider = (el, text, isControl) => {
    if (!text || !text.trim() || hidden(el)) return;
    if (el.closest('[disabled], :disabled, [aria-disabled=true]')) return; /* WCAG exempts disabled controls */
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const cs = getComputedStyle(el);
    const svg = el instanceof SVGElement;
    let fg = parse(svg ? cs.fill : cs.color);
    if (!fg) return;
    const op = opacityOf(el);
    fg = [fg[0], fg[1], fg[2], fg[3] * op];
    const b = background(el);
    const snippet = text.trim().replace(/\s+/g, ' ').slice(0, 50);
    if (/^(undefined|null|NaN|\[object Object\])$/.test(snippet) || /\b(undefined|NaN|\[object Object\])\b/.test(snippet)) bad.push({ where: desc(el), text: snippet });
    if (b.unknown) { unknownBg.push({ where: desc(el), text: snippet, bg: b.unknown }); return; }
    const fgc = over(fg, b.color);
    const ratioV = ratio(fgc, b.color);
    const size = parseFloat(cs.fontSize);
    const weight = Number(cs.fontWeight) || 400;
    const large = size >= 24 || (weight >= 700 && size >= 18.66);
    const need = large ? 3 : 4.5;
    if (ratioV < need) {
      const k = desc(el) + '|' + hex(fgc) + '|' + hex(b.color);
      if (seen.has(k)) return;
      seen.add(k);
      contrast.push({ where: desc(el), text: snippet, fg: hex(fgc), bg: hex(b.color), ratio: Math.round(ratioV * 100) / 100, need, control: !!isControl });
    }
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'OPTION'].includes(el.tagName)) continue;
    if (!n.textContent.trim()) continue;
    consider(el, n.textContent);
    /* text rectangles for the overlap check */
    if (!hidden(el) && !fixedAncestor(el)) {
      const range = document.createRange();
      range.selectNodeContents(n);
      /* one rectangle per line box, so wrapped inline text does not count as a block */
      for (const rr of range.getClientRects()) {
        if (rr.width <= 1 || rr.height <= 1) continue;
        const c = clipRect(el, rr);
        if (c.w > 1 && c.h > 1) texts.push({ el, rect: c, text: n.textContent.trim().slice(0, 40) });
      }
    }
  }
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]), select, textarea')) {
    const v = el.tagName === 'SELECT' ? el.selectedOptions[0]?.textContent : el.value;
    consider(el, v, true);
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

  /* horizontal overflow and the elements that cause it */
  const sw = document.documentElement.scrollWidth;
  const overflow = [];
  if (sw > vw + 1) {
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 && r.width > 0 && !hidden(el)) {
        let scrolls = false;
        for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
          const ox = getComputedStyle(e).overflowX;
          if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') { scrolls = true; break; }
        }
        if (!scrolls && !(el.parentElement && el.parentElement.getBoundingClientRect().right > vw + 1 && overflow.length)) overflow.push({ where: desc(el), right: Math.round(r.right) });
        if (overflow.length >= 5) break;
      }
    }
  }

  const images = [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && !hidden(i)).map((i) => ({ where: desc(i), src: (i.currentSrc || i.src).slice(0, 120) }));
  const main = document.querySelector('.bo-main, .pt-main, .pub-main, main') || document.body;
  const mainText = (main.innerText || '').replace(/\s+/g, ' ').trim();
  const problems = [...document.querySelectorAll('.error-box')].filter((e) => !hidden(e)).map((e) => e.innerText.replace(/\s+/g, ' ').slice(0, 140));
  return {
    contrast, overlaps, overflow: sw > vw + 1 ? { scrollWidth: sw, width: vw, culprits: overflow } : null,
    images, bad, unknownBg: unknownBg.slice(0, 5), mainLength: mainText.length, mainText: mainText.slice(0, 160),
    hasEmpty: !!main.querySelector('.card, .error-box, .banner-info, [data-empty], [role=status], [role=alert], p'),
    loading: !!main.querySelector('[aria-busy=true], .skeleton'),
    problems,
    title: document.title,
  };
}

/* ---------- driver ---------- */
async function signIn(context, base, role) {
  if (!role.email) return;
  await context.request.get(base + '/v1/auth/csrf');
  const csrf = async () => (await context.cookies(base)).find((c) => c.name === 'csrftoken')?.value || '';
  const body = { email: role.email, password: PASSWORD };
  if (role.mfa) body.code = totp(MFA_SECRET);
  let r = await context.request.post(base + '/v1/auth/login', { data: body, headers: { 'X-CSRFToken': await csrf(), Origin: base, Referer: base + '/' } });
  if (!r.ok() && role.mfa) {
    body.code = totp(MFA_SECRET, Date.now() + 30000);
    r = await context.request.post(base + '/v1/auth/login', { data: body, headers: { 'X-CSRFToken': await csrf(), Origin: base, Referer: base + '/' } });
  }
  if (!r.ok() && !role.mfa && args['api-log']) {
    // Clients sign in with a code by SMS (FR-ACC-015). In development the fake SMS adapter writes the text to
    // the API's log; pass that file with --api-log to read the code.
    const p = await r.json().catch(() => ({}));
    if (p.code === 'mfa-required' && p.method === 'sms') {
      await new Promise((ok) => setTimeout(ok, 300));
      const lines = fs.readFileSync(args['api-log'], 'utf8').split('\n').filter((l) => /\[sms\].*code to sign in is \d{6}/.test(l));
      const m = /code to sign in is (\d{6})/.exec(lines[lines.length - 1] || '');
      if (m) r = await context.request.post(base + '/v1/auth/login', { data: { ...body, code: m[1] }, headers: { 'X-CSRFToken': await csrf(), Origin: base, Referer: base + '/' } });
    }
  }
  if (!r.ok()) throw new Error(`sign-in failed for ${role.email}: ${r.status()} ${await r.text()}`);
  await context.request.get(base + '/v1/auth/csrf');
}

async function settle(page) {
  const until = Date.now() + SETTLE_MS;
  await page.waitForLoadState('domcontentloaded').catch(() => undefined);
  await page.waitForTimeout(400);
  while (Date.now() < until) {
    const busy = await page.evaluate(() => {
      const m = document.querySelector('.bo-main, .pt-main, .pub-main, main') || document.body;
      return !!m.querySelector('[aria-busy=true], .skeleton') || (m.innerText || '').trim() === '' || /^Starting/.test((document.body.innerText || '').trim());
    }).catch(() => true);
    if (!busy) break;
    await page.waitForTimeout(250);
  }
  await page.waitForTimeout(250);
}

async function auditPage(page, pageLog) {
  const out = {};
  for (const m of MODES) {
    await page.setViewportSize({ width: m.width, height: m.height });
    await page.emulateMedia({ colorScheme: m.scheme, reducedMotion: 'reduce' });
    await page.waitForTimeout(120);
    out[m.name] = await page.evaluate(pageChecks);
  }
  out.console = pageLog.splice(0);
  return out;
}

async function runRole(browser, role, allRoutes, results) {
  const base = BASE[role.app];
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
  await signIn(context, base, role);
  const page = await context.newPage();
  const log = [];
  page.on('console', (msg) => { if (msg.type() === 'error') log.push('console: ' + msg.text().slice(0, 200)); });
  page.on('pageerror', (err) => log.push('page error: ' + String(err.message || err).slice(0, 200)));
  page.on('response', (res) => {
    const u = res.url();
    if (u.includes('/v1/') && res.status() >= 400 && !u.endsWith('/v1/me')) log.push(`api ${res.status()}: ${res.request().method()} ${new URL(u).pathname}`);
  });
  const mine = allRoutes.filter((r) => role.sections.some((s) => r.section === s || r.section.startsWith(s + '/') || (s.startsWith('(') && r.section.split('/')[0] === s)));
  const routeOf = (u) => {
    const p = new URL(u).pathname;
    return allRoutes.find((r) => !r.dynamic && r.re.test(p)) || allRoutes.find((r) => r.re.test(p));
  };
  const queue = mine.filter((r) => !r.dynamic).map((r) => ({ url: base + r.pattern, from: '(route)' }));
  const seenKeys = new Set();
  const deadSeen = new Set();
  const dynamicPatterns = new Set(mine.filter((r) => r.dynamic).map((r) => r.pattern));
  const reached = new Set();
  let n = 0;
  while (queue.length && n < MAX_PAGES) {
    const { url, from } = queue.shift();
    const key = keyOf(url);
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);
    n++;
    let res;
    try {
      res = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    } catch (e) {
      results.push({ app: role.app, role: role.key, url, key, error: String(e.message).slice(0, 200) });
      continue;
    }
    await settle(page);
    const finalUrl = page.url();
    const route = routeOf(finalUrl);
    if (route) reached.add(route.pattern);
    /* closed <details> hide content the person can open: audit it open */
    await page.evaluate(() => document.querySelectorAll('details').forEach((d) => { d.open = true; })).catch(() => undefined);
    const entry = { app: role.app, role: role.key, url: url.replace(base, ''), finalUrl: finalUrl.replace(base, ''), from: from.replace(base, ''), key, route: route?.pattern, status: res?.status(), checks: await auditPage(page, log), tabs: {}, dead: [] };
    /* in-page tabs (buttons with role=tab) */
    const tabCount = await page.locator('[role=tab]').count();
    for (let t = 1; t < Math.min(tabCount, 10); t++) {
      const tab = page.locator('[role=tab]').nth(t);
      const label = ((await tab.innerText().catch(() => '')) || `tab ${t}`).trim().slice(0, 30);
      try { await tab.click({ timeout: 3000 }); await settle(page); entry.tabs[label] = await auditPage(page, log); } catch { /* tab gone */ }
    }
    results.push(entry);
    process.stdout.write(`${role.app}/${role.key} ${entry.finalUrl}\n`);
    /* follow same-origin links */
    const hrefs = await page.$$eval('a[href]', (as) => as.map((a) => a.href)).catch(() => []);
    for (const h of hrefs) {
      if (!h.startsWith(base) || h.includes('/v1/') || /\.(pdf|png|jpg|zip)$/.test(h)) continue;
      const r = routeOf(h);
      if (!r) {
        /* a link to a page that does not exist in the app */
        const p = new URL(h).pathname;
        if (!deadSeen.has(p)) { deadSeen.add(p); entry.dead.push(p); }
        continue;
      }
      if (!mine.includes(r)) continue;
      if (!seenKeys.has(keyOf(h))) queue.push({ url: h.split('#')[0], from: finalUrl });
    }
    /* clickable table rows lead to detail pages */
    const rows = page.locator('tr.clickable');
    if (await rows.count()) {
      const before = page.url();
      try {
        await rows.first().click({ timeout: 3000 });
        await page.waitForURL((u) => u.toString() !== before, { timeout: 5000 });
        const h = page.url();
        if (!seenKeys.has(keyOf(h))) queue.unshift({ url: h, from: before + ' (row)' });
      } catch { /* row did not navigate */ }
    }
  }
  results.push({ app: role.app, role: role.key, coverage: { visited: n, unreachedDynamic: [...dynamicPatterns].filter((p) => !reached.has(p)) } });
  await context.close();
}

/* ---------- report ---------- */
function summarise(results) {
  const findings = [];
  const add = (f) => findings.push(f);
  for (const r of results) {
    if (r.coverage) continue;
    if (r.error) { add({ kind: 'navigation', page: r.key, role: `${r.app}/${r.role}`, mode: '-', detail: r.error }); continue; }
    const views = [['', r.checks], ...Object.entries(r.tabs).map(([t, c]) => [` (tab ${t})`, c])];
    for (const [suffix, checks] of views) {
      const page = r.key + suffix;
      const who = `${r.app}/${r.role}`;
      for (const m of MODES) {
        const c = checks[m.name];
        if (!c) continue;
        for (const x of c.contrast) add({ kind: 'contrast', page, role: who, mode: m.name, detail: `${x.ratio}:1 (needs ${x.need}) ${x.fg} on ${x.bg} "${x.text}" at ${x.where}`, sig: `${x.where}|${x.fg}|${x.bg}` });
        if (c.overflow && m.width === 390) add({ kind: 'overflow', page, role: who, mode: m.name, detail: `page ${c.overflow.scrollWidth}px wide at ${c.overflow.width}px: ${c.overflow.culprits.map((o) => `${o.where} (right ${o.right})`).join('; ')}`, sig: 'overflow' });
        for (const o of c.overlaps) add({ kind: 'overlap', page, role: who, mode: m.name, detail: `"${o.at}" (${o.a}) overlaps "${o.bt}" (${o.b})`, sig: o.a + o.b });
        for (const i of c.images) add({ kind: 'broken-image', page, role: who, mode: m.name, detail: `${i.src} at ${i.where}`, sig: i.src });
        for (const b of c.bad) add({ kind: 'bad-text', page, role: who, mode: m.name, detail: `"${b.text}" at ${b.where}`, sig: b.where + b.text });
      }
      const c = checks['desktop-light'] || checks[MODES[0].name];
      if (c.loading) add({ kind: 'still-loading', page, role: who, mode: 'all', detail: `still loading after ${SETTLE_MS / 1000} s`, sig: 'loading' });
      else if (c.mainLength < 40 && !c.hasEmpty) add({ kind: 'empty', page, role: who, mode: 'all', detail: `main area shows only "${c.mainText}"`, sig: 'empty' });
      for (const p of c.problems) add({ kind: 'problem-shown', page, role: who, mode: 'all', detail: `${p} (reached from ${r.from})`, sig: p });
    }
    for (const d of r.dead || []) add({ kind: 'dead-link', page: r.key, role: `${r.app}/${r.role}`, mode: 'all', detail: `links to ${d}, which is not a page of the app`, sig: d });
    for (const l of [...new Set(r.checks.console || [])]) add({ kind: 'console', page: r.key, role: `${r.app}/${r.role}`, mode: 'all', detail: l, sig: l });
  }
  /* merge identical findings across modes */
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
  const views = pages.reduce((n, r) => n + 1 + Object.keys(r.tabs).length, 0);
  const kinds = ['contrast', 'overflow', 'overlap', 'broken-image', 'bad-text', 'empty', 'still-loading', 'dead-link', 'navigation', 'problem-shown', 'console'];
  const blocking = new Set(['contrast', 'overflow', 'overlap', 'broken-image', 'bad-text', 'empty', 'still-loading', 'dead-link', 'navigation']);
  const lines = [];
  lines.push('# UI audit report', '');
  lines.push(`Run ${started.toISOString().slice(0, 16).replace('T', ' ')} UTC by \`scripts/ui-audit/audit.js\` against the seeded development data (\`seed_dev\`).`);
  lines.push(`Modes: ${MODES.map((m) => `${m.width}x${m.height} ${m.scheme}`).join(', ')}. Contrast threshold 4.5:1, or 3:1 for text 24 px and up or bold 18.66 px and up.`, '');
  lines.push(`Pages visited: ${pages.length} (${views} views including in-page tabs), each checked in ${MODES.length} modes.`, '');
  lines.push('| Check | Findings |', '|---|---|');
  for (const k of kinds) lines.push(`| ${k}${blocking.has(k) ? '' : ' (for information)'} | ${findings.filter((f) => f.kind === k).length} |`);
  lines.push('');
  for (const k of kinds) {
    const fs_ = findings.filter((f) => f.kind === k);
    if (!fs_.length) continue;
    lines.push(`## ${k}`, '');
    for (const f of fs_.slice(0, 300)) lines.push(`- \`${f.page}\` as ${f.role} [${f.modes}]: ${f.detail.replace(/\|/g, '\\|')}`);
    if (fs_.length > 300) lines.push(`- … and ${fs_.length - 300} more`);
    lines.push('');
  }
  lines.push('## Coverage', '');
  for (const r of results.filter((x) => x.coverage)) {
    lines.push(`- ${r.app}/${r.role}: ${r.coverage.visited} pages.${r.coverage.unreachedDynamic.length ? ` Detail routes with no link from the seeded data: ${r.coverage.unreachedDynamic.map((p) => `\`${p}\``).join(', ')}.` : ''}`);
  }
  lines.push('');
  return lines.join('\n');
}

(async () => {
  const started = new Date();
  const only = args.app;
  const roleKeys = args.roles ? args.roles.split(',') : null;
  const all = { portal: routes('portal'), backoffice: routes('backoffice') };
  const browser = await chromium.launch();
  const results = [];
  for (const role of ROLES) {
    if (only && role.app !== only) continue;
    if (roleKeys && !roleKeys.includes(role.key)) continue;
    try {
      await runRole(browser, role, all[role.app], results);
    } catch (e) {
      results.push({ app: role.app, role: role.key, url: '(sign in)', key: '(sign in)', error: String(e.message).slice(0, 300) });
    }
  }
  await browser.close();
  const findings = summarise(results);
  const md = report(results, findings, started);
  const out = args.out || path.join(__dirname, 'report.md');
  fs.writeFileSync(out, md);
  if (args.json) fs.writeFileSync(args.json, JSON.stringify({ results, findings }, null, 1));
  const blocking = findings.filter((f) => !['problem-shown', 'console'].includes(f.kind));
  console.log(`\n${findings.length} findings (${blocking.length} blocking). Report: ${path.relative(process.cwd(), out)}`);
  process.exitCode = blocking.length ? 1 : 0;
})();
