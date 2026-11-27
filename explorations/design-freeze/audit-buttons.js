// Clicks every visible button and link in each prototype section and lists the ones that change nothing ("dead").
// Usage: python3 -m http.server 8790 (in this folder), then: node audit-buttons.js http://127.0.0.1:8790/index.html [fonts.css fonts-dir]
// (name index.html in the URL: the page declares no charset, and only that path is served as UTF-8 here)
// The two font arguments are only for machines that cannot reach Google Fonts; they serve the fonts locally.
// SECS=s-mobile,s-desk node audit-buttons.js … audits only those sections.
const { chromium } = require('playwright'); const fs = require('fs');
// What a click can change: the section's markup (hashed, not just its length: toggling a class keeps the length),
// the URL hash, the page, the toast, the scroll position, and the pixels of every map canvas in the section
// (zoom and reset buttons change only those).
const SNAP = s => { const h = t => { let x = 0; for (let i = 0; i < t.length; i++) x = (x * 31 + t.charCodeAt(i)) | 0; return x; };
  const r = document.getElementById(s);
  return [h(r.innerHTML), location.hash, document.body.innerHTML.length, (document.querySelector('[data-mtoast]') || {}).innerHTML || '', window.scrollY,
    ...[...r.querySelectorAll('canvas')].map(c => { try { return h(c.toDataURL()); } catch (e) { return 0; } })]; };
(async () => { const [url, cssF, FD] = process.argv.slice(2), css = cssF ? fs.readFileSync(cssF, 'utf8') : null;
  const b = await chromium.launch(); const results = [];
  const secs = process.env.SECS ? process.env.SECS.split(',') : ['s-start', 's-mobile', 's-desk', 's-phone', 's-life', 's-topics', 's-guess', 's-cards', 's-duel', 's-archive', 's-share', 's-xiang', 's-gujin', 's-gov', 's-time'];
  for (const sec of secs) {
    const p = await b.newPage({ viewport: { width: 1400, height: 1000 } }); const errs = [];
    p.on('pageerror', e => errs.push(String(e).slice(0, 160)));
    if (css) await p.route('https://fonts.googleapis.com/**', r => r.fulfill({ status: 200, contentType: 'text/css', body: css }));
    if (css) await p.route('**/__fonts/**', r => { const rel = decodeURIComponent(new URL(r.request().url()).pathname.replace('/__fonts/', '')); try { r.fulfill({ status: 200, contentType: 'font/woff2', body: fs.readFileSync(FD + '/' + rel) }); } catch (e) { r.fulfill({ status: 404, body: '' }); } });
    await p.route('**/index.html', async r => { const res = await r.fetch(); r.fulfill({ response: res, headers: { ...res.headers(), 'content-type': 'text/html; charset=utf-8' } }); });
    await p.goto(url, { waitUntil: 'load' }); await p.waitForTimeout(9000);
    // skip mobile onboarding so its buttons are reachable
    if (sec === 's-mobile') { const sk = await p.$('#s-mobile [data-m="skip-ob"]'); if (sk) { await sk.click(); await p.waitForTimeout(400); } for (let i = 0; i < 3; i++) { const c = await p.$('#s-mobile [data-m="coach-next"]'); if (c) { await c.click(); await p.waitForTimeout(150); } } }
    const n = await p.evaluate(s => { const root = document.getElementById(s); const els = [...root.querySelectorAll('button, [role=button], a[href]')].filter(e => e.offsetParent && !e.closest('.sec-head')); els.forEach((e, i) => e.setAttribute('data-audit', s + '-' + i)); return els.length; }, sec);
    let dead = [];
    for (let i = 0; i < n; i++) { const sel = `[data-audit="${sec}-${i}"]`; const el = await p.$(sel); if (!el) continue; const vis = await el.isVisible().catch(() => false); if (!vis) continue;
      const label = (await el.evaluate(e => (e.getAttribute('aria-label') || e.textContent || e.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 40))) || '?';
      const idle = await p.evaluate(SNAP, sec); await p.waitForTimeout(350); const before = await p.evaluate(SNAP, sec);
      const still = before.map((v, k) => v === idle[k]);  // parts that change on their own (animated canvases) prove nothing
      let dl = false; p.once('download', () => dl = true);
      // A real click first (pointer events, like a person). If something an earlier click opened covers the button,
      // fire the button's own click instead: the question is whether the button is wired, not what lies on top.
      try { await el.click({ timeout: 1500 }); } catch (e) { try { await el.evaluate(x => x.click()); } catch (e2) { continue; } }
      await p.waitForTimeout(350);
      const after = await p.evaluate(SNAP, sec);
      const changed = before.some((v, k) => still[k] && v !== after[k]) || after.length !== before.length || dl;
      if (!changed) dead.push(label); }
    results.push([sec, n, dead, errs.slice(0, 3)]); console.log(sec, n, 'dead:', JSON.stringify(dead), errs.length ? 'ERR ' + JSON.stringify(errs.slice(0, 2)) : ''); await p.close(); }
  await b.close(); })();
