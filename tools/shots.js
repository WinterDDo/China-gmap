#!/usr/bin/env node
// 一键截图：手机（375×667）和桌面（1440×900），中文和 EN，各截一张，再拼成一张对照图。
// 「测试绿不等于做完」：改了界面就跑一次，自己先看，要用户拍板时把对照图给他。
//
//   node tools/shots.js                      每种组合截第一屏
//   node tools/shots.js s-duel s-archive     截定稿原型里的指定区块（<section id="s-…">）
//
// 注意：定稿原型是一份设计规范页，多数区块里放的是桌面界面的等比缩小图；在手机宽度下
// 截到的也是缩小图。要看真正的手机界面，截 s-mobile（手机版完整体验）和 s-phone。
//
//   --dir <目录>   起本地服务的静态目录（默认 explorations/design-freeze）
//   --url <网址>   直接截这个网址，不起服务
//   --out <目录>   输出目录（默认 shots/，不进仓库）
//   --wait <毫秒>  页面加载完再等多久，让地图和动画画完（默认 2500）
//
// 页面报错会在最后列出来，并以非零状态退出：截出来的图可能是坏的。

const { chromium } = require('playwright');
const fs = require('fs');
const http = require('http');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const VIEWS = [
  { key: 'phone', label: '手机 375', viewport: { width: 375, height: 667 }, isMobile: true, hasTouch: true },
  { key: 'desk', label: '桌面 1440', viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false },
];
const LANGS = [{ key: 'zh', label: '中文' }, { key: 'en', label: 'EN' }];
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon',
};

function parseArgs(argv) {
  const opts = { dir: 'explorations/design-freeze', url: null, out: 'shots', wait: 2500, sections: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--dir') opts.dir = argv[++i];
    else if (a === '--url') opts.url = argv[++i];
    else if (a === '--out') opts.out = argv[++i];
    else if (a === '--wait') opts.wait = Number(argv[++i]);
    else if (a.startsWith('--')) throw new Error(`不认识的选项：${a}`);
    else opts.sections.push(a);
  }
  return opts;
}

function serve(dir) {
  const base = path.resolve(ROOT, dir);
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let file = path.join(base, rel.endsWith('/') ? rel + 'index.html' : rel);
    if (!file.startsWith(base)) { res.writeHead(403).end(); return; }
    fs.readFile(file, (err, body) => {
      if (err) { res.writeHead(404).end(); return; }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream' });
      res.end(body);
    });
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function setLanguage(page, lang) {
  const ok = await page.evaluate(l => {
    if (typeof window.setLang === 'function') { window.setLang(l); return true; }
    const b = document.querySelector(`[data-set-lang="${l}"]`);
    if (b) { b.click(); return true; }
    return false;
  }, lang);
  if (!ok) throw new Error(`页面上找不到切换到「${lang}」的办法（没有 setLang，也没有 data-set-lang 按钮）`);
}

async function contactSheet(browser, target, shots, file) {
  const img = p => `data:image/png;base64,${fs.readFileSync(p).toString('base64')}`;
  const cell = s => `<figure><figcaption>${s.view.label} · ${s.lang.label}</figcaption><img src="${img(s.file)}" style="width:${s.view.key === 'phone' ? 375 : 720}px"></figure>`;
  const rows = VIEWS.map(v => `<div class="row">${shots.filter(s => s.view.key === v.key).map(cell).join('')}</div>`).join('');
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;padding:24px;background:#e9e4d8;font:14px/1.4 sans-serif;color:#2b231d}
    h1{font-size:16px;margin:0 0 16px}.row{display:flex;gap:24px;align-items:flex-start;margin-bottom:24px}
    figure{margin:0}figcaption{margin-bottom:6px;font-weight:600}img{display:block;box-shadow:0 1px 4px rgba(0,0,0,.25)}
  </style><h1>${target}</h1>${rows}`;
  const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 1520, height: 600 } });
  await page.setContent(html);
  await page.screenshot({ path: file, fullPage: true });
  await page.close();
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const out = path.resolve(ROOT, opts.out);
  fs.mkdirSync(out, { recursive: true });
  const server = opts.url ? null : await serve(opts.dir);
  const url = opts.url || `http://127.0.0.1:${server.address().port}/`;
  const targets = opts.sections.length ? opts.sections : ['page'];
  const browser = await chromium.launch();
  const errors = [];
  const shots = Object.fromEntries(targets.map(t => [t, []]));

  try {
    for (const view of VIEWS) {
      // One load per viewport; switching language re-renders in place, which is much faster.
      const ctx = await browser.newContext({
        viewport: view.viewport, deviceScaleFactor: 2, isMobile: view.isMobile, hasTouch: view.hasTouch,
      });
      const page = await ctx.newPage();
      page.on('pageerror', e => errors.push(`${view.label}：${String(e).slice(0, 200)}`));
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
      for (const lang of LANGS) {
        await setLanguage(page, lang.key);
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(opts.wait);
        for (const target of targets) {
          const file = path.join(out, `${target}-${view.key}-${lang.key}.png`);
          if (target === 'page') {
            await page.screenshot({ path: file });
          } else {
            const el = await page.$(`#${target}`);
            if (!el) throw new Error(`页面上没有 id 为「${target}」的区块`);
            await el.scrollIntoViewIfNeeded();
            await page.waitForTimeout(400);
            await el.screenshot({ path: file });
          }
          shots[target].push({ view, lang, file });
        }
      }
      await ctx.close();
    }
    for (const target of targets) {
      const sheet = path.join(out, `${target}-sheet.png`);
      await contactSheet(browser, target, shots[target], sheet);
      console.log(`${target}：4 张截图 + 对照图 ${path.relative(ROOT, sheet)}`);
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }

  if (errors.length) {
    console.error(`\n页面报错 ${errors.length} 条（截图可能不对，先查清）：`);
    for (const e of [...new Set(errors)]) console.error('  ' + e);
    process.exit(1);
  }
}

main().catch(e => { console.error(String(e.message || e)); process.exit(1); });
