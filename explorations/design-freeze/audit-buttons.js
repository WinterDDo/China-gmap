const { chromium } = require('playwright'); const fs = require('fs');
(async () => { const [url, cssF, FD] = process.argv.slice(2), css = fs.readFileSync(cssF, 'utf8');
  const b = await chromium.launch(); const results = [];
  const secs = ['s-start', 's-mobile', 's-desk', 's-phone', 's-life', 's-topics', 's-guess', 's-cards', 's-duel', 's-archive', 's-share', 's-xiang', 's-gujin', 's-gov', 's-time'];
  for (const sec of secs) {
    const p = await b.newPage({ viewport: { width: 1400, height: 1000 } }); const errs = [];
    p.on('pageerror', e => errs.push(String(e).slice(0, 160)));
    await p.route('https://fonts.googleapis.com/**', r => r.fulfill({ status: 200, contentType: 'text/css', body: css }));
    await p.route('**/__fonts/**', r => { const rel = decodeURIComponent(new URL(r.request().url()).pathname.replace('/__fonts/', '')); try { r.fulfill({ status: 200, contentType: 'font/woff2', body: fs.readFileSync(FD + '/' + rel) }); } catch (e) { r.fulfill({ status: 404, body: '' }); } });
    await p.route('**/index.html', async r => { const res = await r.fetch(); r.fulfill({ response: res, headers: { ...res.headers(), 'content-type': 'text/html; charset=utf-8' } }); });
    await p.goto(url, { waitUntil: 'load' }); await p.waitForTimeout(9000);
    // skip mobile onboarding so its buttons are reachable
    if (sec === 's-mobile') { const sk = await p.$('#s-mobile [data-m="skip-ob"]'); if (sk) { await sk.click(); await p.waitForTimeout(400); } for (let i = 0; i < 3; i++) { const c = await p.$('#s-mobile [data-m="coach-next"]'); if (c) { await c.click(); await p.waitForTimeout(150); } } }
    const n = await p.evaluate(s => { const root = document.getElementById(s); const els = [...root.querySelectorAll('button, [role=button], a[href]')].filter(e => e.offsetParent && !e.closest('.sec-head')); els.forEach((e, i) => e.setAttribute('data-audit', s + '-' + i)); return els.length; }, sec);
    let dead = [];
    for (let i = 0; i < n; i++) { const sel = `[data-audit="${sec}-${i}"]`; const el = await p.$(sel); if (!el) continue; const vis = await el.isVisible().catch(() => false); if (!vis) continue;
      const label = (await el.evaluate(e => (e.getAttribute('aria-label') || e.textContent || e.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 40))) || '?';
      const before = await p.evaluate(s => { const r = document.getElementById(s); return [r.innerHTML.length, location.hash, document.body.innerHTML.length, (document.querySelector('[data-mtoast]') || {}).innerHTML || '', window.scrollY]; }, sec);
      let dl = false; p.once('download', () => dl = true);
      try { await el.click({ timeout: 1500, force: true }); } catch (e) { continue; }
      await p.waitForTimeout(350);
      const after = await p.evaluate(s => { const r = document.getElementById(s); return [r.innerHTML.length, location.hash, document.body.innerHTML.length, (document.querySelector('[data-mtoast]') || {}).innerHTML || '', window.scrollY]; }, sec);
      const changed = before.some((v, k) => v !== after[k]) || dl;
      if (!changed) dead.push(label); }
    results.push([sec, n, dead, errs.slice(0, 3)]); console.log(sec, n, 'dead:', JSON.stringify(dead), errs.length ? 'ERR ' + JSON.stringify(errs.slice(0, 2)) : ''); await p.close(); }
  await b.close(); })();
