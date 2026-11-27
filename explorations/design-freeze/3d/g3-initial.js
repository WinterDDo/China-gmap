/* ================= 立体江山 · 3D 试做 ================= */
const G3 = { ready: false, failed: false, mode: "terrain", k: 22, ex: 0, sel: null, hover: null, dev: "desk", LW: 1440, LH: 900, u: 1, dirty: true, visible: false, tween: null, idle: 0, lastT: 0,
  cam: { tx: 0, tz: 0, dist: 7600, az: 0, tilt: 0 }, prisms: null, rise: 0, pts: [], cloudA: 0, dimT: 0 };
const G3PAL = ["#e3d2a4", "#bfc493", "#7ea88b", "#3d8177", "#1f586d"];
const G3MODES = [["terrain", ["地貌", "Terrain"]], ["pop", ["人口", "Population"]], ["month", ["每月收入", "Income"]], ["pc", ["人均 GDP", "GDP / head"]]];
function g3Load() { return new Promise((res, rej) => { if (window.THREE) return res(); const s = document.createElement("script"); s.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"; s.crossOrigin = "anonymous"; s.referrerPolicy = "no-referrer"; const to = setTimeout(() => rej(new Error("timeout")), 20000); s.onload = () => { clearTimeout(to); res(); }; s.onerror = () => { clearTimeout(to); rej(new Error("load")); }; document.head.appendChild(s); }); }
function g3GL() { try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; } }
function g3Fail(msg) { G3.failed = true; const st = $("[data-g3stage]"); if (st) st.innerHTML = `<div class="g3-fail">${seal("立体")}<b>${ZH("这台设备打不开立体视图", "3D view isn't available on this device")}</b><span>${msg}</span><span class="note">${ZH("正式版会自动回到平面地图，内容和玩法都一样。", "The real site falls back to the flat map with the same content.")}</span></div>`; }
async function g3Init() { const st = $("[data-g3stage]"); if (!st) return; g3Hud();
  if (!g3GL()) return g3Fail(ZH("浏览器没有开启 WebGL", "WebGL is off in this browser"));
  try { await g3Load(); } catch (e) { return g3Fail(ZH("三维组件没加载下来（网络）", "The 3D library didn't load (network)")); }
  const T = THREE, W = FR.w, H = FR.h; G3.T = T;
  const R = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" }); G3.R = R; R.setClearColor(0x000000, 0); R.domElement.className = "g3-gl"; st.appendChild(R.domElement);
  const ov = document.createElement("canvas"); ov.className = "g3-ov"; ov.tabIndex = 0; ov.setAttribute("aria-label", ZH("立体地图：拖动平移，右键或双指旋转，滚轮或双指缩放", "3D map: drag to pan, right-drag or two fingers to rotate, wheel or pinch to zoom")); st.appendChild(ov); G3.ov = ov;
  const scene = new T.Scene(); G3.scene = scene; scene.fog = new T.Fog(0xe9dfc8, 5000, 16000);
  const cam = new T.PerspectiveCamera(32, 1.6, 20, 60000); G3.camera = cam;
  scene.add(new T.AmbientLight(0xffffff, .78)); const sun = new T.DirectionalLight(0xfff1dc, .5); sun.position.set(-1, 1.25, -1); scene.add(sun); G3.sun = sun;
  // --- painted base as the terrain texture (same art as the flat map) ---
  const TW = Math.min(4096, R.capabilities.maxTextureSize), TH = Math.round(TW * H / W), tc = document.createElement("canvas"); tc.width = TW; tc.height = TH;
  const fake = { base: tc, bctx: tc.getContext("2d"), u: 2.4 * TW / 4096, view: { s: TW / W, ox: 0, oy: 0 }, cfg: { lens: () => "none" }, zoom: () => 2, home: { s: TW / W } };
  renderBase(fake);
  const map = new T.CanvasTexture(tc); map.anisotropy = R.capabilities.getMaxAnisotropy(); map.minFilter = T.LinearMipmapLinearFilter;
  // --- relief from real elevation (DEM, 4 km cells), averaged onto the mesh grid ---
  const coarse = matchMedia("(pointer: coarse)").matches, SX = coarse ? 300 : 440, SY = Math.round(SX * H / W), geo = new T.PlaneGeometry(W, H, SX, SY); geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position, hs = new Float32Array((SX + 1) * (SY + 1)), cw = W / SX / DEM.km, chh = H / SY / DEM.km;
  for (let j = 0; j <= SY; j++) for (let i = 0; i <= SX; i++) { let s = 0, n = 0; const cx = i * cw, cy = j * chh, r = Math.max(1, Math.floor(cw / 2));
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) { const x = Math.round(cx + dx), y = Math.round(cy + dy); if (x >= 0 && y >= 0 && x < DEM.w && y < DEM.h) { s += Math.max(0, DEM.z[y * DEM.w + x]); n++; } }
    const e = i === 0 || j === 0 || i === SX || j === SY ? 0 : (n ? s / n : 0) / 1000; hs[j * (SX + 1) + i] = e; pos.setY(j * (SX + 1) + i, e); }
  geo.computeVertexNormals(); G3.hs = hs; G3.SX = SX; G3.SY = SY;
  const tmat = new T.MeshLambertMaterial({ map }); tmat.color.setScalar(.92); const terr = new T.Mesh(geo, tmat); scene.add(terr); G3.terr = terr; terr.scale.y = .001;
  // --- the board: layered paper edge, mounting frame, soft shadow ---
  const sideCv = document.createElement("canvas"); sideCv.width = 8; sideCv.height = 128; const sx = sideCv.getContext("2d"); const gr = sx.createLinearGradient(0, 0, 0, 128);
  gr.addColorStop(0, "#5a3c2a"); gr.addColorStop(.08, "#5a3c2a"); gr.addColorStop(.09, "#c9a96e"); gr.addColorStop(.13, "#c9a96e"); gr.addColorStop(.14, "#efe4cc"); gr.addColorStop(.86, "#e3d4b4"); gr.addColorStop(.9, "#7a5a42"); gr.addColorStop(1, "#4a3224"); sx.fillStyle = gr; sx.fillRect(0, 0, 8, 128);
  for (let y = 20; y < 108; y += 7) { sx.fillStyle = "rgba(120,90,60,.12)"; sx.fillRect(0, y, 8, 1); }
  const sideMat = new T.MeshLambertMaterial({ map: new T.CanvasTexture(sideCv) }), dark = new T.MeshLambertMaterial({ color: 0x3a2a20 }), BT = 150;
  const board = new T.Mesh(new T.BoxGeometry(W, BT, H), [sideMat, sideMat, dark, dark, sideMat, sideMat]); board.position.y = -BT / 2 - .2; scene.add(board);
  const fw = 70, fh = 9, fmat = new T.MeshLambertMaterial({ color: 0x5b3f2d }), fgold = new T.MeshLambertMaterial({ color: 0xc2a065 });
  [[W + 2 * fw, fw, 0, -H / 2 - fw / 2], [W + 2 * fw, fw, 0, H / 2 + fw / 2], [fw, H, -W / 2 - fw / 2, 0], [fw, H, W / 2 + fw / 2, 0]].forEach(([a, b, x, z]) => { const m = new T.Mesh(new T.BoxGeometry(a, fh, b), [fmat, fmat, fgold, fmat, fmat, fmat]); m.position.set(x, fh / 2 - 1, z); scene.add(m); const s = new T.Mesh(new T.BoxGeometry(a, BT, b), fmat); s.position.set(x, -BT / 2 - 1, z); scene.add(s); });
  const shCv = document.createElement("canvas"); shCv.width = shCv.height = 256; const shx = shCv.getContext("2d"), rg = shx.createRadialGradient(128, 128, 40, 128, 128, 128); rg.addColorStop(0, "rgba(40,28,18,.55)"); rg.addColorStop(1, "rgba(40,28,18,0)"); shx.fillStyle = rg; shx.fillRect(0, 0, 256, 256);
  const shadow = new T.Mesh(new T.PlaneGeometry(W * 1.45, H * 1.45), new T.MeshBasicMaterial({ map: new T.CanvasTexture(shCv), transparent: true, depthWrite: false, fog: false })); shadow.rotation.x = -Math.PI / 2; shadow.position.set(120, -BT - 30, 160); scene.add(shadow);
  // --- clouds drifting between the peaks ---
  const imgs = (FX.imgs && FX.imgs.length) ? FX.imgs : [0, 1, 2].map(() => cloudSprite(rng(9))), r = rng(31); G3.clouds = [];
  const ctex = imgs.map(im => new T.CanvasTexture(im));
  for (let i = 0; i < 26; i++) { const m = new T.SpriteMaterial({ map: ctex[i % ctex.length], transparent: true, depthWrite: false, opacity: 0, fog: true }), sp = new T.Sprite(m), s = 420 + r() * 520;
    let x, z; for (let k = 0; k < 20; k++) { x = 1400 + r() * 3900; z = 900 + r() * 3200; const gi = Math.round(z / H * SY) * (SX + 1) + Math.round(x / W * SX); if (hs[gi] > .9 || k > 14) break; }
    sp.position.set(x - W / 2, 0, z - H / 2); sp.userData = { base: 60 + r() * 90, v: 6 + r() * 10, s }; sp.scale.set(s, s * .42, 1); scene.add(sp); G3.clouds.push(sp); }
  // --- selected-city ring ---
  const ring = new T.Mesh(new T.RingGeometry(16, 24, 48), new T.MeshBasicMaterial({ color: 0xb23a2b, transparent: true, opacity: .85, side: T.DoubleSide, depthWrite: false, fog: false })); ring.rotation.x = -Math.PI / 2; ring.visible = false; scene.add(ring); G3.ring = ring;
  // nation bbox → home view
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const poly of G.nation) for (const ringP of poly) for (const [x, y] of ringP) { if (x < x0) x0 = x; if (y < y0) y0 = y; if (x > x1) x1 = x; if (y > y1) y1 = y; }
  G3.nat = { cx: (x0 + x1) / 2 - W / 2, cz: (y0 + y1) / 2 - H / 2 + 120, w: x1 - x0, h: y1 - y0 };
  g3Bind(); g3Resize(); G3.ready = true; st.classList.add("ready");
  const io = new IntersectionObserver(es => { for (const e of es) { G3.visible = e.isIntersecting; if (G3.visible && !G3.opened) { G3.opened = true; g3Opening(); } } }, { threshold: .15 }); io.observe(st);
  requestAnimationFrame(g3Loop); }
/* ---------- camera ---------- */
function g3Home() { const ph = G3.dev === "phone"; return { tx: G3.nat.cx + (ph ? 150 : -60), tz: G3.nat.cz + (ph ? 260 : 60), dist: ph ? 10400 : 6300, az: -.1, tilt: ph ? .9 : .92 }; }
function g3Apply() { const c = G3.cam, cam = G3.camera, st = Math.sin(c.tilt), ct = Math.cos(c.tilt);
  cam.position.set(c.tx + c.dist * st * Math.sin(c.az), c.dist * ct + 30, c.tz + c.dist * st * Math.cos(c.az)); cam.lookAt(c.tx, 0, c.tz);
  const f = G3.scene.fog; f.near = c.dist * .55; f.far = c.dist * (2.1 + (1 - c.tilt) * 2); G3.dirty = true; }
function g3Clamp() { const c = G3.cam, W = FR.w / 2, H = FR.h / 2; c.dist = clamp(c.dist, 650, 12500); c.tilt = clamp(c.tilt, 0, 1.18); c.tx = clamp(c.tx, -W * .8, W * .8); c.tz = clamp(c.tz, -H * .8, H * .8); }
const g3Ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
function g3Tween(to, dur = 900, extra) { const from = { ...G3.cam, ex: G3.ex, cloudA: G3.cloudA, rise: G3.rise, dimT: G3.dimT }; let da = (to.az ?? from.az) - from.az; while (da > Math.PI) da -= 2 * Math.PI; while (da < -Math.PI) da += 2 * Math.PI; if (to.az != null) to.az = from.az + da;
  G3.tween = { from, to, t0: performance.now(), dur: RM() ? 1 : dur, extra }; }
function g3Opening() { const h = g3Home(); G3.sel = null; G3.ring.visible = false; g3Card(); Object.assign(G3.cam, { ...h, dist: h.dist * 1.25, tilt: 0, az: 0 }); G3.ex = 0; G3.cloudA = 0; G3.idle = performance.now() + 3000; g3Apply(); g3Tween({ ...h, ex: G3.mode === "terrain" ? 1 : .02, cloudA: G3.mode === "terrain" ? 1 : .25 }, 3000); }
/* ---------- height under a map point (same grid as the mesh) ---------- */
function g3H(x, y) { const fx = clamp(x / FR.w * G3.SX, 0, G3.SX - .001), fy = clamp(y / FR.h * G3.SY, 0, G3.SY - .001), i = fx | 0, j = fy | 0, a = fx - i, b = fy - j, n = G3.SX + 1, h = G3.hs;
  return (h[j * n + i] * (1 - a) + h[j * n + i + 1] * a) * (1 - b) + (h[(j + 1) * n + i] * (1 - a) + h[(j + 1) * n + i + 1] * a) * b; }
/* ---------- data prisms (prefectures rise by value) ---------- */
function g3Val(c, m) { return !c ? null : m === "pop" ? c.popAny : m === "month" ? c.month : m === "pc" ? c.pc : null; }
function g3Prisms() { if (G3.prisms) return G3.prisms; const T = G3.T, W = FR.w, H = FR.h, list = [];
  P.prefs.forEach((p, i) => { const c = PREF_CITY[i]; const shapes = [];
    for (const poly of p.rings) { const ring = poly[0]; if (!ring || ring.length < 4) continue; const pts = []; let lx = 1e9, ly = 1e9;
      for (const [x, y] of ring) { if (Math.hypot(x - lx, y - ly) < 5) continue; pts.push(new T.Vector2(x - W / 2, -(y - H / 2))); lx = x; ly = y; }
      if (pts.length >= 3) shapes.push(new T.Shape(pts)); }
    if (!shapes.length) return; const g = new T.ExtrudeGeometry(shapes, { depth: 1, bevelEnabled: false }); g.rotateX(-Math.PI / 2);
    const top = new T.MeshLambertMaterial({ color: 0xcccccc }), side = new T.MeshLambertMaterial({ color: 0x999999 }), m = new T.Mesh(g, [top, side]); m.scale.y = .001; m.visible = false; m.userData = { i, c, name: p.name }; G3.scene.add(m); list.push(m); });
  return G3.prisms = list; }
function g3SetMode(m) { if (!G3.ready || m === G3.mode) return; G3.mode = m; G3.hover = null; g3Hud();
  if (m === "terrain") { g3Tween({ ex: 1, cloudA: 1, rise: 0, dimT: 0 }, 1100, () => { (G3.prisms || []).forEach(x => x.visible = false); }); snd("flip"); return; }
  const L = LENSES[m], ps = g3Prisms(), vals = CITIES.map(c => g3Val(c, m)).filter(v => v != null && isFinite(v)), mx = Math.max(...vals), mn = Math.min(...vals), cols = G3PAL.map(h => new G3.T.Color(h));
  const order = ps.map(p => g3Val(p.userData.c, m)).filter(v => v != null).sort((a, b) => a - b);
  for (const p of ps) { const v = g3Val(p.userData.c, m); if (v == null || !isFinite(v)) { p.visible = false; p.userData.h = 0; continue; }
    const n = m === "pop" ? Math.pow(v / mx, .8) : Math.pow((v - mn) / (mx - mn || 1), 1.15), k = lensClass(L, p.userData.c);
    p.userData.h = 14 + n * (m === "pop" ? 560 : 430); p.userData.delay = order.indexOf(v) / order.length * .55; p.userData.v = v;
    p.material[0].color.copy(cols[Math.max(0, k)]); p.material[1].color.copy(cols[Math.max(0, k)]).multiplyScalar(.7); p.visible = true; p.scale.y = .001; }
  G3.rise = 0; const c = G3.cam; g3Tween({ ex: .02, cloudA: .2, rise: 1, dimT: 1, tilt: Math.max(c.tilt, .82) }, 1600); snd("flip"); }
/* ---------- overlay: towns, plaques, data labels (flat, always face you) ---------- */
function g3Overlay() { const ov = G3.ov, ctx = ov.getContext("2d"), u = G3.u, OW = ov.width, OH = ov.height, cam = G3.camera, v = new G3.T.Vector3(), c3 = G3.cam;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, OW, OH); G3.pts = []; const Lb = Labeler(OW, OH);
  const proj = (x, y, z) => { v.set(x, y, z); const d = v.distanceTo(cam.position); v.project(cam); if (v.z > 1 || v.x < -1.15 || v.x > 1.15 || v.y < -1.15 || v.y > 1.15) return null; return [(v.x + 1) / 2 * OW, (1 - v.y) / 2 * OH, d]; };
  if (G3.mode !== "terrain") { if (G3.rise < .6) return; const L = LENSES[G3.mode], seen = new Set(), arr = [];
    for (const p of G3.prisms || []) { const c = p.userData.c; if (!p.visible || !c || seen.has(c.id)) continue; seen.add(c.id); const q = proj(c.x - FR.w / 2, p.scale.y + 4, c.y - FR.h / 2); if (q) arr.push([c, q, p.userData.v]); }
    arr.sort((a, b) => b[2] - a[2]); let n = 0; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    for (const [c, [x, y], val] of arr) { if (n >= (c3.dist > 5000 ? 12 : 28)) break; const t = `${cname(c)} ${L.fmt(val)}`; ctx.font = `600 ${12 * u}px "Noto Serif SC", serif`; const w = ctx.measureText(t).width + 12 * u, b = [x - w / 2, y - 22 * u, w, 18 * u];
      if (!Lb.free(b)) continue; Lb.add(b); n++; ctx.fillStyle = "rgba(251,244,230,.92)"; ctx.strokeStyle = "rgba(43,35,29,.5)"; ctx.lineWidth = u; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(b[0], b[1], b[2], b[3], 3 * u) : ctx.rect(b[0], b[1], b[2], b[3]); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x, y - 4 * u); ctx.lineTo(x, y + 2 * u); ctx.stroke(); ctx.fillStyle = "#2b231d"; ctx.fillText(t, x, y - 6 * u); G3.pts.push({ c, x, y, rect: b }); }
    if (G3.hover && G3.hover.m) { const hm = G3.hover; const t1 = hm.name, t2 = hm.c ? `${t(L.name)} · ${hm.v != null ? L.fmt(hm.v) : ZH("没数据", "no data")}` : ZH("没数据，不立柱", "no data"); ctx.font = `600 ${13 * u}px "Noto Serif SC", serif`; const w = Math.max(ctx.measureText(t1).width, ctx.measureText(t2).width * .9) + 20 * u, x = clamp(hm.x + 14 * u, 4, OW - w - 4), y = clamp(hm.y - 50 * u, 4, OH - 50 * u);
      ctx.fillStyle = "rgba(32,24,18,.92)"; ctx.fillRect(x, y, w, 44 * u); ctx.fillStyle = "#f6efe0"; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(t1, x + 10 * u, y + 7 * u); ctx.font = `500 ${11.5 * u}px "Noto Sans SC", sans-serif`; ctx.fillStyle = "#e5d6b8"; ctx.fillText(t2, x + 10 * u, y + 25 * u); }
    return; }
  if (G3.ex < .3) return; const far = c3.dist > 5200, minTier = c3.dist > 7000 ? 2 : far ? 1 : 0, quota = c3.dist > 7000 ? 8 : far ? 14 : c3.dist > 2600 ? 30 : 90, ex = G3.terr.scale.y;
  const P2 = []; for (const c of CITIES) { const q = proj(c.x - FR.w / 2, g3H(c.x, c.y) * ex + 2, c.y - FR.h / 2); if (q) P2.push({ c, x: q[0], y: q[1], d: q[2], k: clamp(c3.dist / q[2], .55, 1.45) }); }
  const sel = G3.sel, kz = clamp(.62 * Math.pow(6300 / c3.dist, .5), .55, 1.5) * u;
  // towns far → near
  for (const p of P2.slice().sort((a, b) => b.d - a.d)) { if (p.c.tier < minTier && p.c.id !== sel) { if (c3.dist < 7000) { ctx.fillStyle = "rgba(178,58,43,.75)"; ctx.beginPath(); ctx.arc(p.x, p.y, 1.6 * u, 0, 7); ctx.fill(); } continue; } drawTown(ctx, p.x, p.y, p.c.tier, kz * p.k); }
  // plaques by importance, scaled by depth
  const order = P2.slice().sort((a, b) => (b.c.id === sel) - (a.c.id === sel) || (a.c.gdpIdx ?? 999) - (b.c.gdpIdx ?? 999)); let n = 0; const drawn = [];
  for (const p of order) { const isSel = p.c.id === sel; if (!isSel && (n >= quota || p.c.tier < minTier)) continue; const bu = u * clamp(p.k, .78, 1.25), m = bannerMetrics(ctx, p.c, bu), by = p.y - TOWN_H[p.c.tier] * kz * p.k - 4 * u, box = [p.x - m.w / 2 - 2 * u, by - m.h - 2 * u, m.w + 4 * u, m.h + 4 * u];
    if (!isSel && !Lb.free(box)) continue; Lb.add(box); n++; drawn.push([p, by, bu, isSel]); }
  for (const [p, by, bu, isSel] of drawn.reverse()) { const rect = drawBanner(ctx, p.c, p.x, by, bu, { selected: isSel, yields: isSel }); G3.pts.push({ c: p.c, x: p.x, y: p.y, rect }); if (isSel) drawSeal(ctx, rect[0] - 13 * bu, rect[1] + 9 * bu, 22 * bu, p.c.id === (M.home || V4.home) ? "吾乡" : p.c.n.slice(0, 2), bu, 7); }
  for (const p of P2) if (!G3.pts.some(q => q.c === p.c)) G3.pts.push({ c: p.c, x: p.x, y: p.y }); }
/* ---------- loop ---------- */
function g3Loop(now) { requestAnimationFrame(g3Loop); if (!G3.ready || !G3.visible) { G3.lastT = now; return; } const dt = Math.min(.1, (now - (G3.lastT || now)) / 1000); G3.lastT = now;
  const tw = G3.tween; if (tw) { const p = clamp((now - tw.t0) / tw.dur, 0, 1), e = g3Ease(p);
    for (const k of ["tx", "tz", "dist", "az", "tilt"]) if (tw.to[k] != null) G3.cam[k] = tw.from[k] + (tw.to[k] - tw.from[k]) * e;
    for (const k of ["ex", "cloudA", "rise", "dimT"]) if (tw.to[k] != null) G3[k] = tw.from[k] + (tw.to[k] - tw.from[k]) * e;
    g3Apply(); if (p >= 1) { G3.tween = null; if (tw.extra) tw.extra(); } }
  else if (!RM() && G3.mode === "terrain" && !G3.sel && now - G3.idle > 9000) { G3.cam.az += dt * .018; g3Apply(); }
  G3.terr.scale.y = Math.max(.001, G3.ex * G3.k); G3.terr.material.color.setScalar(.92 - G3.dimT * .22);
  if (G3.prisms) for (const p of G3.prisms) if (p.visible) { const r = clamp((G3.rise - p.userData.delay) / .45, 0, 1), e = 1 + 2.4 * Math.pow(r - 1, 3) + 1.4 * Math.pow(r - 1, 2); p.scale.y = Math.max(.001, p.userData.h * e); p.position.y = 1; }
  const cA = G3.cloudA * clamp((G3.cam.dist - 900) / 1800, 0, 1);
  for (const s of G3.clouds) { const ud = s.userData; s.position.x += ud.v * dt; if (s.position.x > FR.w / 2 - 300) s.position.x = -FR.w / 2 + 300; s.position.y = (ud.base + 40) * Math.max(G3.terr.scale.y / G3.k, .3); const dc = s.position.distanceTo(G3.camera.position); s.material.opacity = cA * .9 * clamp((dc - 500) / 900, 0, 1); }
  if (G3.ring.visible) { const s = 1 + .25 * Math.sin(now / 300); G3.ring.scale.set(s, s, s); G3.ring.material.opacity = .55 + .3 * Math.sin(now / 300); const c = BYID.get(G3.sel); if (c) G3.ring.position.set(c.x - FR.w / 2, g3H(c.x, c.y) * G3.terr.scale.y + 2, c.y - FR.h / 2); }
  G3.R.render(G3.scene, G3.camera); if (G3.dirty || tw || G3.hover) { g3Overlay(); G3.dirty = false; } }
/* ---------- size / device ---------- */
function g3Resize() { if (!G3.R) return; const ph = G3.dev === "phone"; G3.LW = ph ? 390 : 1440; G3.LH = ph ? 844 : 900; const dpr = Math.min(window.devicePixelRatio || 1, 2), host = $("[data-g3stage]"), box = host.getBoundingClientRect(), sc = box.width ? box.width / G3.LW : 1;
  const pr = clamp(dpr * sc, 1, ph ? 2.4 : 1.6); G3.u = pr; G3.R.setPixelRatio(pr); G3.R.setSize(G3.LW, G3.LH, false); G3.ov.width = Math.round(G3.LW * pr); G3.ov.height = Math.round(G3.LH * pr);
  G3.camera.aspect = G3.LW / G3.LH; G3.camera.updateProjectionMatrix(); g3Apply(); }
function g3SetDev(d) { if (d === G3.dev) return; G3.dev = d; const app = $("[data-app=g3]"), dest = $(d === "phone" ? "[data-g3phone] .screen" : "[data-g3desk] .screen"); if (app && dest) dest.appendChild(app);
  $("[data-g3desk]").hidden = d === "phone"; $("[data-g3phonewrap]").hidden = d !== "phone"; app.classList.toggle("ph", d === "phone"); $$("[data-g3-dev]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.g3Dev === d)));
  scaleScreens(); g3Resize(); if (G3.ready) { Object.assign(G3.cam, g3Home()); g3Apply(); } g3Hud(); }
/* ---------- HUD + card ---------- */
function g3Hud() { const el = $("[data-g3hud]"); if (!el) return; const m = G3.mode, L = m !== "terrain" && LENSES[m], ph = G3.dev === "phone";
  el.innerHTML = `<div class="g3-top"><span class="brand-lock"><span class="seal"><span>图鉴</span></span><span class="wordmark"><b>江山图鉴</b><i>JIANGSHAN ATLAS</i></span></span><div class="g3-modes" role="group" aria-label="${ZH("看什么", "Show")}">${G3MODES.map(([k, lab]) => `<button class="chip ${k === m ? "on" : ""}" data-g3mode="${k}" aria-pressed="${k === m}">${ZH(...lab)}</button>`).join("")}</div></div>
    <div class="g3-ctl"><button class="btn icon" data-g3="in" aria-label="${ZH("放大", "Zoom in")}">${icon("i-plus")}</button><button class="btn icon" data-g3="out" aria-label="${ZH("缩小", "Zoom out")}">${icon("i-minus")}</button><button class="btn icon" data-g3="rl" aria-label="${ZH("向左转", "Rotate left")}">⟲</button><button class="btn icon" data-g3="rr" aria-label="${ZH("向右转", "Rotate right")}">⟳</button><button class="btn icon" data-g3="tilt" aria-label="${ZH("俯视 / 立体", "Top / tilted")}" title="${ZH("俯视 / 立体", "Top / tilted")}">${G3.cam.tilt > .3 ? ZH("俯", "2D") : ZH("立", "3D")}</button><button class="btn icon" data-g3="home" aria-label="${ZH("回到全国", "Whole country")}">${icon("i-compass")}</button></div>
    ${L ? `<div class="g3-legend"><b>${t(L.name)}</b><span>${ZH("柱越高，数越大；没数据的地方不立柱", "Taller = larger; no data, no column")}</span><div class="sw">${G3PAL.map((c, i) => `<i style="background:${c}"></i>`).join("")}</div><div class="lb">${lensLabels(L).map(x => `<span>${x}</span>`).join("")}</div></div>`
      : `<div class="g3-legend g3-hint"><b>${ZH("真实高程 · 竖向夸张", "Real elevation, exaggerated")} ×${G3.k}</b><span>${ph ? ZH("单指拖动 · 双指缩放、转动、上下推改倾角", "One finger pans · two fingers zoom, turn, tilt") : ZH("拖动平移 · 右键拖动（或按住 Shift）转动和倾斜 · 滚轮缩放 · 点城市飞过去", "Drag to pan · right-drag (or Shift) to turn and tilt · wheel to zoom · click a city to fly there")}</span><label class="g3-k">${ZH("山势", "Relief")}<input type="range" min="6" max="40" step="1" value="${G3.k}" data-g3k aria-label="${ZH("山势夸张倍数", "Vertical exaggeration")}"></label></div>`}
    <div class="g3-card" data-g3card hidden></div>`;
  if (G3.sel) g3Card(); }
function g3Card() { const el = $("[data-g3card]"); if (!el) return; const c = G3.sel && BYID.get(G3.sel); if (!c) { el.hidden = true; return; } el.hidden = false; const e = g3H(c.x, c.y);
  el.innerHTML = `<button class="btn icon ghost close" data-g3="close" aria-label="${ZH("关闭", "Close")}">${icon("i-close")}</button><div class="cp-head" style="grid-template-columns:auto 1fr"><span class="seal stamp"><span>${c.n.slice(0, 2)}</span></span><div><h2 style="font-size:24px">${cname(c)}</h2><div class="meta">${pvOf(c)} · ${kindOf(c)} · ${ZH(`海拔约 ${Math.round(e * 1000).toLocaleString("en-US")} 米`, `about ${Math.round(e * 1000).toLocaleString("en-US")} m up`)}</div></div></div>${prideHTML(c, 2, true)}
    <div class="row-gap"><button class="btn primary" data-g3="open">${ZH("看完整档案", "Open the archive")}</button><button class="btn" data-g3="home">${ZH("回到全国", "Whole country")}</button></div>`; }
function g3Select(id) { const c = BYID.get(id); if (!c) return; G3.sel = id; G3.ring.visible = true; mVisit(id); g3Card(); snd("stamp"); const cs = $("[data-g3card] .seal"); if (cs) spatter(cs, 14);
  const ph = G3.dev === "phone"; g3Tween({ tx: c.x - FR.w / 2 + (ph ? 0 : 130), tz: c.y - FR.h / 2 + (ph ? 160 : 40), dist: ph ? 1900 : 1500, tilt: 1.0, ex: G3.mode === "terrain" ? 1 : G3.ex }, 1500); }
/* ---------- input ---------- */
function g3Bind() { const ov = G3.ov, pts = new Map(); let drag = null, moved = 0, pinch = null;
  const loc = e => { const r = ov.getBoundingClientRect(); return [(e.clientX - r.left) * G3.LW / r.width, (e.clientY - r.top) * G3.LH / r.height]; };
  const wpp = () => 2 * G3.cam.dist * Math.tan(16 * Math.PI / 180) / G3.LH;
  const pan = (dx, dy) => { const c = G3.cam, k = wpp(), kk = k / Math.max(.45, Math.cos(c.tilt)); c.tx -= (Math.cos(c.az) * dx) * k + (Math.sin(c.az) * dy) * kk; c.tz -= (-Math.sin(c.az) * dx) * k + (Math.cos(c.az) * dy) * kk; };
  const touchy = () => { G3.idle = performance.now(); const tw = G3.tween; if (tw) for (const k of ["tx", "tz", "dist", "az", "tilt"]) delete tw.to[k]; };
  ov.addEventListener("contextmenu", e => e.preventDefault());
  ov.addEventListener("pointerdown", e => { ov.setPointerCapture(e.pointerId); pts.set(e.pointerId, loc(e)); touchy();
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, ang: Math.atan2(b[1] - a[1], b[0] - a[0]), my: (a[1] + b[1]) / 2, c: { ...G3.cam } }; drag = null; moved = 99; return; }
    drag = { p: loc(e), rot: e.button === 2 || e.shiftKey || e.ctrlKey || e.altKey }; moved = 0; });
  ov.addEventListener("pointermove", e => { const q = loc(e); if (pts.has(e.pointerId)) pts.set(e.pointerId, q);
    if (pinch && pts.size >= 2) { const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, ang = Math.atan2(b[1] - a[1], b[0] - a[0]), my = (a[1] + b[1]) / 2;
      G3.cam.dist = pinch.c.dist * pinch.d / d; G3.cam.az = pinch.c.az - (ang - pinch.ang); G3.cam.tilt = pinch.c.tilt - (my - pinch.my) * .006; g3Clamp(); g3Apply(); return; }
    if (drag) { const dx = q[0] - drag.p[0], dy = q[1] - drag.p[1]; moved += Math.abs(dx) + Math.abs(dy); drag.p = q; if (moved < 4) return;
      if (drag.rot) { G3.cam.az -= dx * .005; G3.cam.tilt = G3.cam.tilt + dy * .004; } else pan(dx, dy); g3Clamp(); g3Apply(); ov.style.cursor = "grabbing"; return; }
    // hover
    if (G3.mode !== "terrain" && G3.prisms) { const r = ov.getBoundingClientRect(), nx = (e.clientX - r.left) / r.width * 2 - 1, ny = -((e.clientY - r.top) / r.height * 2 - 1), rc = new G3.T.Raycaster(); rc.setFromCamera({ x: nx, y: ny }, G3.camera);
      const hit = rc.intersectObjects(G3.prisms.filter(p => p.visible), false)[0]; const u = G3.u; G3.hover = hit ? { m: 1, name: hit.object.userData.c ? cname(hit.object.userData.c) : hit.object.userData.name, c: hit.object.userData.c, v: hit.object.userData.v, x: q[0] * u, y: q[1] * u } : null; G3.dirty = true; }
    else { const h = g3Hit(q); ov.style.cursor = h ? "pointer" : "grab"; } });
  const up = e => { pts.delete(e.pointerId); ov.style.cursor = ""; if (pinch) { if (pts.size < 2) pinch = null; drag = null; return; } if (!drag) return; const was = moved >= 4; drag = null; if (was) return;
    const h = G3.mode !== "terrain" && G3.hover && G3.hover.c ? { c: G3.hover.c } : g3Hit(loc(e)); if (h) { spatterAt(e.clientX, e.clientY, 12); g3Select(h.c.id); } };
  ov.addEventListener("pointerup", up); ov.addEventListener("pointercancel", up);
  ov.addEventListener("wheel", e => { e.preventDefault(); touchy(); G3.cam.dist *= Math.exp(e.deltaY * .0012); g3Clamp(); g3Apply(); }, { passive: false });
  ov.addEventListener("dblclick", () => { touchy(); g3Tween({ dist: G3.cam.dist / 1.8 }, 450); });
  ov.addEventListener("keydown", e => { const c = G3.cam, k = { ArrowLeft: [-60, 0], ArrowRight: [60, 0], ArrowUp: [0, -60], ArrowDown: [0, 60] }[e.key]; touchy();
    if (k) { pan(-k[0], -k[1]); e.preventDefault(); } else if (e.key === "+" || e.key === "=") c.dist /= 1.3; else if (e.key === "-") c.dist *= 1.3; else if (e.key === "q") c.az += .2; else if (e.key === "e") c.az -= .2; else if (e.key === "t") c.tilt = c.tilt > .3 ? 0 : .95; else return; g3Clamp(); g3Apply(); });
  document.addEventListener("click", e => { const b = e.target.closest("[data-g3],[data-g3mode],[data-g3-dev]"); if (!b) return; if (b.dataset.g3Dev) { g3SetDev(b.dataset.g3Dev); return; } if (!G3.ready) return; touchy();
    if (b.dataset.g3mode) { g3SetMode(b.dataset.g3mode); return; } const k = b.dataset.g3, c = G3.cam;
    if (k === "in") g3Tween({ dist: c.dist / 1.6 }, 450); else if (k === "out") g3Tween({ dist: Math.min(12500, c.dist * 1.6) }, 450); else if (k === "rl") g3Tween({ az: c.az + Math.PI / 4 }, 600); else if (k === "rr") g3Tween({ az: c.az - Math.PI / 4 }, 600);
    else if (k === "tilt") { g3Tween({ tilt: c.tilt > .3 ? 0 : .95, az: c.tilt > .3 ? 0 : c.az }, 800, g3Hud); }
    else if (k === "home") { G3.sel = null; G3.ring.visible = false; g3Card(); g3Tween(g3Home(), 1200); }
    else if (k === "close") { G3.sel = null; G3.ring.visible = false; g3Card(); }
    else if (k === "replay") { g3SetMode("terrain"); G3.opened = true; g3Opening(); }
    else if (k === "open" && G3.sel) { const id = G3.sel; try { history.pushState({ d: 1 }, "", "#d/" + id); } catch (x) { } dRestore("#d/" + id); const sd = document.getElementById("s-desk"); if (sd) sd.scrollIntoView({ behavior: RM() ? "auto" : "smooth" }); } });
  document.addEventListener("input", e => { if (e.target.matches && e.target.matches("[data-g3k]")) { G3.k = +e.target.value; const b = e.target.closest(".g3-legend").querySelector("b"); if (b) b.textContent = ZH("真实高程 · 竖向夸张", "Real elevation, exaggerated") + " ×" + G3.k; G3.dirty = true; } });
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(g3Resize, 260); }); }
function g3Hit(q) { const u = G3.u, X = q[0] * u, Y = q[1] * u; let best = null, bd = 1e9;
  for (const p of G3.pts) { if (p.rect) { const [x, y, w, h] = p.rect; if (X >= x && X <= x + w && Y >= y && Y <= y + h) return p; } }
  for (const p of G3.pts) { const d = Math.hypot(p.x - X, p.y - Y); if (d < 16 * u && d < bd) { bd = d; best = p; } } return best; }
