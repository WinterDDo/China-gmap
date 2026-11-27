/* ================= 导演 · 镜头语言（电影感转场） ================= */
const DIR = { seq: 0, scene: null, focus: .46, band: .3, blur: 0, speed: 0, lastPos: null, wipe: null, towers: null, su: null, round: null, score: [0, 0], focusPt: null };
const G3FS = `uniform sampler2D tDiffuse; uniform vec2 uRes; uniform float uFocus; uniform float uBand; uniform float uBlur; uniform float uVig; uniform float uTime; uniform float uGrain; uniform float uWarm; varying vec2 vUv;
float rnd(vec2 c) { return fract(sin(dot(c, vec2(12.9898, 78.233))) * 43758.5453); }
void main() { float d = max(0., abs(vUv.y - uFocus) - uBand); float r = clamp(d * 3.2, 0., 1.) * uBlur; vec4 c = texture2D(tDiffuse, vUv);
  if (r > .35) { vec4 acc = c; for (int i = 1; i < 16; i++) { float a = float(i) * 2.39996; float rr = sqrt(float(i) / 16.); acc += texture2D(tDiffuse, vUv + vec2(cos(a), sin(a)) * rr * r / uRes); } c = acc / 16.; }
  vec2 q = vUv - .5; float v = smoothstep(.92, .3, length(q * vec2(1., .92))); c.rgb *= mix(1., .82 + .18 * v, uVig);
  c.rgb = mix(c.rgb, c.rgb * vec3(1.035, 1.0, .95) + vec3(.012, .006, 0.), uWarm);
  c.rgb += (rnd(vUv * uRes + fract(uTime)) - .5) * uGrain; gl_FragColor = vec4(c.rgb, 1.); }`;
function g3Post() { const T = G3.T, R = G3.R; try {
    const RT = R.capabilities.isWebGL2 && T.WebGLMultisampleRenderTarget ? T.WebGLMultisampleRenderTarget : T.WebGLRenderTarget;
    G3.rt = new RT(4, 4, { minFilter: T.LinearFilter, magFilter: T.LinearFilter, format: T.RGBAFormat }); if ("samples" in G3.rt) G3.rt.samples = 4;
    G3.pmat = new T.ShaderMaterial({ uniforms: { tDiffuse: { value: G3.rt.texture }, uRes: { value: new T.Vector2(4, 4) }, uFocus: { value: .46 }, uBand: { value: .3 }, uBlur: { value: 0 }, uVig: { value: 1 }, uTime: { value: 0 }, uGrain: { value: .018 }, uWarm: { value: .7 } },
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }", fragmentShader: G3FS, depthTest: false, depthWrite: false });
    G3.pscene = new T.Scene(); G3.pcam = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1); const q = new T.Mesh(new T.PlaneGeometry(2, 2), G3.pmat); q.frustumCulled = false; G3.pscene.add(q);
  } catch (e) { G3.rt = null; } }
function g3PostSize() { if (!G3.rt) return; const v = new G3.T.Vector2(); G3.R.getDrawingBufferSize(v); G3.rt.setSize(v.x, v.y); G3.pmat.uniforms.uRes.value.copy(v); }
function g3Render(now) { const R = G3.R; if (!G3.rt) { R.render(G3.scene, G3.camera); return; } const U = G3.pmat.uniforms; U.uFocus.value = DIR.focus; U.uBand.value = DIR.band; U.uBlur.value = DIR.blur * G3.u; U.uTime.value = now / 1000;
  R.setRenderTarget(G3.rt); R.render(G3.scene, G3.camera); R.setRenderTarget(null); R.render(G3.pscene, G3.pcam); }
/* ---------- per-frame direction: focus pulls, motion blur, wipes, towers, route ---------- */
function g3DirFrame(now, dt) { const cam = G3.camera, c3 = G3.cam, p = cam.position;
  if (DIR.lastPos) { const sp = p.distanceTo(DIR.lastPos) / Math.max(dt, .016) / c3.dist; DIR.speed = DIR.speed * .75 + sp * .25; DIR.lastPos.copy(p); } else DIR.lastPos = p.clone();
  const flat = c3.tilt < .3; let fy = .46; const band = flat ? .7 : c3.dist < 2600 ? .13 : .2, base = flat ? 0 : c3.dist < 2600 ? 2.3 : 1.3;
  const fp = DIR.focusPt || (G3.sel && BYID.get(G3.sel)); if (fp && !flat) { const v = new G3.T.Vector3(fp.x - FR.w / 2, g3H(fp.x, fp.y) * G3.terr.scale.y, fp.y - FR.h / 2).project(cam); if (v.z < 1 && Math.abs(v.y) < 1) fy = (v.y + 1) / 2; }
  const k = 1 - Math.pow(.03, dt); DIR.focus += (fy - DIR.focus) * k; DIR.band += (band - DIR.band) * k; DIR.blur += (base + clamp(DIR.speed * 10, 0, 7) - DIR.blur) * Math.min(1, k * 1.8);
  g3WipeFrame(now);
  if (DIR.towers) for (const t of DIR.towers) { if (t.anim) { const q = clamp((now - t.anim.t0) / t.anim.dur, 0, 1), e = q <= 0 ? 0 : 1 + 2.2 * Math.pow(q - 1, 3) + 1.2 * Math.pow(q - 1, 2); t.h = t.anim.from + (t.anim.to - t.anim.from) * e; if (q >= 1) t.anim = null; G3.dirty = true; }
    t.col.scale.y = Math.max(.001, t.h); t.roof.position.y = t.base + t.h; t.glow.material.opacity = t.win ? .4 + .25 * Math.sin(now / 160) : 0; }
  if (DIR.su && DIR.su.anim) { const a = DIR.su.anim, q = clamp((now - a.t0) / a.dur, 0, 1); g3SuDraw(a.u0 + (a.u1 - a.u0) * g3Ease(q)); if (q >= 1) DIR.su.anim = null; }
  g3CardPos(); }
/* ---------- cloud wipe: fly through painted clouds between far-apart shots ---------- */
function g3Wipe(t0, dur) { DIR.wipe = { t0, dur }; }
function g3WipeFrame(now) { const cv = G3.fxc; if (!cv) return; const x = cv.getContext("2d"), W = cv.width, H = cv.height, w = DIR.wipe;
  if (!w) { if (DIR.wipeDrawn) { x.clearRect(0, 0, W, H); DIR.wipeDrawn = 0; } return; } const q = (now - w.t0) / w.dur; x.clearRect(0, 0, W, H); if (q < 0) return; if (q > 1) { DIR.wipe = null; return; } DIR.wipeDrawn = 1;
  const a = Math.sin(Math.PI * q), S = W / 1440 * 1.8;
  for (const c of G3.wipeC) { const g = .2 + q * 2.4, px = W / 2 + c.x * g * W * .5, py = H / 2 + c.y * g * H * .5, img = G3.cloudImgs[c.i], s = (.5 + q * 2.8) * c.s * S; x.globalAlpha = Math.min(1, a * c.a * 1.2); x.drawImage(img, px - img.width * s / 2, py - img.height * s / 2, img.width * s, img.height * s); }
  x.globalAlpha = Math.pow(a, 2.4) * .72; x.fillStyle = "#f5efe1"; x.fillRect(0, 0, W, H); x.globalAlpha = 1; }
/* ---------- cinema chrome: letterbox, title cards, score, skip ---------- */
function g3Cine(on) { const app = $("[data-app=g3]"); if (app) app.classList.toggle("cine", !!on); const sk = $("[data-g3skip]"); if (sk) sk.hidden = !on; }
function g3Title(html, ms = 2200, cls = "") { const el = $("[data-g3title]"); if (!el) return; clearTimeout(g3Title.t); clearTimeout(g3Title.t2); el.className = "g3-titlec " + cls; el.innerHTML = html; el.hidden = false; void el.offsetWidth; el.classList.add("in");
  g3Title.t = setTimeout(() => { el.classList.remove("in"); el.classList.add("out"); g3Title.t2 = setTimeout(() => { el.hidden = true; }, 650); }, RM() ? Math.min(ms, 1600) : ms); }
function g3TitleOff() { const el = $("[data-g3title]"); if (el) { clearTimeout(g3Title.t); el.hidden = true; el.className = "g3-titlec"; } }
function g3Score() { const el = $("[data-g3score]"); if (!el) return; if (!DIR.towers) { el.hidden = true; return; } const [a, b] = DIR.towers; el.hidden = false; el.innerHTML = `<span class="a">${cname(a.c)} <b>${DIR.score[0]}</b></span><i>:</i><span class="b"><b>${DIR.score[1]}</b> ${cname(b.c)}</span>`; }
const g3Wait = ms => new Promise(r => setTimeout(r, RM() ? Math.min(ms, 300) : ms));
const g3Ang = a => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
/* ---------- the camera move: arc flight with anticipation, lead and settle ---------- */
function g3Fly(to, o = {}) { return new Promise(res => { const f = { ...G3.cam }, T_ = { tx: to.tx ?? f.tx, tz: to.tz ?? f.tz, dist: to.dist ?? f.dist, tilt: to.tilt ?? f.tilt, az: to.az ?? f.az }, da = g3Ang(T_.az - f.az);
  const D = Math.hypot(T_.tx - f.tx, T_.tz - f.tz), dur = RM() ? 1 : (o.dur ?? clamp(1300 + D * .55, 1300, 3400)), peak = o.arc ?? Math.min(D * .45, 3000), ant = o.ant ?? (D > 800 ? .05 : 0), dip = o.dip ?? (peak > 400 ? .28 : 0);
  const fn = p => { const e = g3Ease(p), el = g3Ease(Math.min(1, p * 1.1)), b = Math.sin(Math.PI * p), a0 = p < .16 ? Math.sin(p / .16 * Math.PI) : 0;
    G3.cam.tx = f.tx + (T_.tx - f.tx) * el; G3.cam.tz = f.tz + (T_.tz - f.tz) * el; G3.cam.dist = f.dist + (T_.dist - f.dist) * e + peak * Math.pow(b, 1.4) + ant * f.dist * a0;
    G3.cam.tilt = f.tilt + (T_.tilt - f.tilt) * e - dip * Math.pow(b, 1.2) * Math.min(f.tilt, T_.tilt, .9) / .9; G3.cam.az = f.az + da * g3Ease(clamp((p - .08) / .84, 0, 1)); g3Clamp(); };
  G3.tween = { fn, t0: performance.now(), dur, to: { ...(o.extra || {}) }, from: { ex: G3.ex, cloudA: G3.cloudA, rise: G3.rise, dimT: G3.dimT }, extra: res };
  if (o.wipe && !RM() && D > 900) g3Wipe(performance.now() + dur * .22, dur * .56); if (D > 600 || o.whoosh) snd("whoosh"); }); }
function g3Cut() { DIR.seq++; DIR.scene = null; DIR.focusPt = null; DIR.round = null; g3Cine(false); g3TitleOff(); g3TowersClear(); if (DIR.su) DIR.su.mesh.visible = false; G3.dirty = true; }
function g3ModeQuick(m) { if (G3.mode === m) return; G3.mode = m; G3.hover = null; if (m === "terrain") { G3.ex = 1; G3.cloudA = 1; G3.rise = 0; G3.dimT = 0; (G3.prisms || []).forEach(x => x.visible = false); } g3Hud(); }
/* ---------- anchored card: lives beside its city, unrolls like a scroll ---------- */
function g3CardPos() { const el = $("[data-g3card]"); if (!el || el.hidden || G3.dev === "phone" || !G3.sel) { G3.cardA = null; return; } const c = BYID.get(G3.sel); if (!c) return;
  const v = new G3.T.Vector3(c.x - FR.w / 2, g3H(c.x, c.y) * G3.terr.scale.y, c.y - FR.h / 2).project(G3.camera), sx = (v.x + 1) / 2 * G3.LW, sy = (1 - v.y) / 2 * G3.LH, w = 340, h = el.offsetHeight || 280;
  let L = sx + 96; if (L + w > G3.LW - 76) L = sx - 96 - w; L = clamp(L, 16, G3.LW - w - 76); const T_ = clamp(sy - h * .42, 70, G3.LH - h - 16);
  el.style.left = L + "px"; el.style.top = T_ + "px"; el.style.right = "auto"; const prev = G3.cardA; G3.cardA = [sx, sy, L, T_, w, h]; if (!prev || Math.abs(prev[0] - sx) + Math.abs(prev[1] - sy) > .5) G3.dirty = true; }
function g3PkPair(c) { const fixed = { "500000": "510100", "510100": "500000", "110000": "310000", "310000": "110000", "120000": "110000", "440300": "440100", "440100": "440300" };
  if (fixed[c.id]) return [c, BYID.get(fixed[c.id])]; const sib = mSibs(c).filter(x => x.id !== c.id); if (sib.length) return [c, sib[0]];
  const near = CITIES.filter(x => x.id !== c.id && x.tier >= 2).sort((a, b) => Math.hypot(a.x - c.x, a.y - c.y) - Math.hypot(b.x - c.x, b.y - c.y)); return [c, near[0]]; }
/* ---------- scene: choose a city ---------- */
async function g3Fly2City(id, o = {}) { const c = BYID.get(id); if (!c) return; const prev = G3.sel && BYID.get(G3.sel); G3.sel = id; mVisit(id); G3.ring.visible = false; const card = $("[data-g3card]"); if (card) card.hidden = true;
  const ph = G3.dev === "phone", cx = c.x - FR.w / 2, cz = c.y - FR.h / 2, D = Math.hypot(cx - G3.cam.tx, cz - G3.cam.tz); let az = G3.cam.az;
  if (o.track && prev) { const dx = c.x - prev.x, dz = c.y - prev.y; if (Math.hypot(dx, dz) > 20) az = G3.cam.az + clamp(g3Ang(Math.atan2(-dx, -dz) - G3.cam.az), -.7, .7) * .6; }
  const dist = 1700, half = dist * Math.tan(G3.camera.fov / 2 * Math.PI / 180), r = [Math.cos(az), -Math.sin(az)], fw = [-Math.sin(az), -Math.cos(az)];
  const sh = ph ? [-fw[0] * half * .42, -fw[1] * half * .42] : [r[0] * half * G3.camera.aspect * .22, r[1] * half * G3.camera.aspect * .22];
  DIR.focusPt = c; const best = prideOf(c)[0];
  setTimeout(() => { if (G3.sel === id) g3Title(`<small>${pvOf(c)}</small><b>${cname(c)}</b>${best ? `<span>${ZH(...best.m.lab)} · ${best.m.ph(c)}</span>` : ""}`, 2000, "city"); }, RM() ? 0 : Math.max(500, (o.track ? 900 : 1300 + D * .3)));
  await g3Fly({ tx: cx + sh[0], tz: cz + sh[1], dist, tilt: .98, az }, o.track ? { dur: clamp(1100 + D * .6, 1100, 2400), arc: Math.min(D * .15, 260), dip: 0, ant: 0 } : { wipe: D > 2200 });
  if (G3.sel !== id) return; DIR.focusPt = null; G3.ring.visible = true; g3Card(true); snd("stamp"); const cs = $("[data-g3card] .seal"); if (cs) spatter(cs, 14); }
/* ---------- scene: PK as a duel between two towers ---------- */
function g3TowersClear() { if (DIR.towers) for (const t of DIR.towers) G3.scene.remove(t.g); DIR.towers = null; DIR.round = null; g3Score(); }
function g3Towers(A, B) { const T = G3.T; g3TowersClear();
  DIR.towers = [A, B].map((c, i) => { const col = new T.Mesh(new T.CylinderGeometry(30, 38, 1, 28, 1).translate(0, .5, 0), new T.MeshLambertMaterial({ color: i ? 0xb23a2b : 0x2f6d6a }));
    const roof = new T.Mesh(new T.ConeGeometry(62, 46, 4).rotateY(Math.PI / 4).translate(0, 23, 0), new T.MeshLambertMaterial({ color: 0x3a2a20 }));
    const glow = new T.Mesh(new T.RingGeometry(58, 120, 48).rotateX(-Math.PI / 2), new T.MeshBasicMaterial({ color: 0xe8b25a, transparent: true, opacity: 0, depthWrite: false, fog: false, side: T.DoubleSide }));
    const g = new T.Group(), base = g3H(c.x, c.y) * G3.terr.scale.y; g.position.set(c.x - FR.w / 2, 0, c.y - FR.h / 2); col.position.y = base; roof.position.y = base; glow.position.y = base + 3; g.add(col, roof, glow); G3.scene.add(g);
    return { c, g, col, roof, glow, base, h: 0, anim: null, win: false, color: i ? "#b23a2b" : "#2f6d6a" }; }); DIR.score = [0, 0]; g3Score(); }
async function g3Duel(aId, bId, tok) { tok = tok ?? (g3Cut(), DIR.seq); const ok = () => tok === DIR.seq, A = BYID.get(aId), B = BYID.get(bId); if (!A || !B) return;
  DIR.scene = "duel"; g3Cine(true); G3.sel = null; G3.ring.visible = false; g3Card(); g3ModeQuick("terrain"); if (DIR.su) DIR.su.mesh.visible = false; g3Towers(A, B); const [ta, tb] = DIR.towers;
  const ax = A.x - FR.w / 2, az0 = A.y - FR.h / 2, bx = B.x - FR.w / 2, bz = B.y - FR.h / 2, dx = bx - ax, dz = bz - az0, L = Math.hypot(dx, dz) || 1; let px = -dz / L, pz = dx / L; if (pz < 0) { px = -px; pz = -pz; }
  const azTwo = Math.atan2(px, pz), mid = { x: (A.x + B.x) / 2, y: (A.y + B.y) / 2 }, two = { tx: (ax + bx) / 2, tz: (az0 + bz) / 2, dist: Math.max(L * 2.1, 1500) + 600, tilt: 1.02, az: azTwo };
  DIR.focusPt = mid; g3Title(`<small>${ZH("城市 PK", "CITY PK")}</small><b>${cname(A)}<i>vs</i>${cname(B)}</b>`, 2300, "big");
  await g3Fly(two, { wipe: true, dur: 2600 }); if (!ok()) return;
  const metrics = [["popAny", ZH("常住人口", "Population"), fmtPopShort], ["month", ZH("每月可支配收入", "Monthly income"), v => FMTS.yuan(v)], ["pc", ZH("人均 GDP", "GDP per head"), fmtPc], ["gdp", ZH("经济总量", "GDP"), fmtYuan], ["forest", ZH("森林占比", "Forest"), v => Math.round(v * 100) + "%"]].filter(([k]) => A[k] != null && B[k] != null).slice(0, 3);
  const nums = ZH(["一", "二", "三"], ["1", "2", "3"]), lowA = { tx: ax, tz: az0, dist: 1150, tilt: 1.14, az: azTwo + .55 }, lowB = { tx: bx, tz: bz, dist: 1150, tilt: 1.14, az: azTwo - .55 };
  for (let i = 0; i < metrics.length; i++) { const [k, lab, f] = metrics[i], va = A[k], vb = B[k], mx = Math.max(va, vb) || 1;
    ta.win = tb.win = false; DIR.round = { lab, f, va, vb, showA: 0, showB: 0 }; g3Title(`<small>${ZH(`第${nums[i]}回合`, `ROUND ${nums[i]}`)}</small><b>${lab}</b>`, 1400);
    ta.anim = { from: ta.h, to: 70 + 520 * va / mx, t0: performance.now() + 500, dur: 1300 }; tb.anim = { from: tb.h, to: 70 + 520 * vb / mx, t0: performance.now() + 1700, dur: 1300 };
    DIR.focusPt = A; await g3Fly(lowA, { dur: 1300, arc: 220, ant: 0, dip: 0 }); if (!ok()) return; DIR.round.showA = 1; G3.dirty = true; await g3Wait(650); if (!ok()) return;
    DIR.focusPt = B; await g3Fly(lowB, { dur: 850, arc: 140, ant: 0, dip: 0, whoosh: 1 }); if (!ok()) return; DIR.round.showB = 1; G3.dirty = true; await g3Wait(650); if (!ok()) return;
    DIR.focusPt = mid; await g3Fly(two, { dur: 1000, arc: 0, ant: 0, dip: 0 }); if (!ok()) return;
    const w = va === vb ? -1 : va > vb ? 0 : 1; if (w >= 0) { DIR.towers[w].win = true; DIR.score[w]++; snd("ok"); } g3Score(); G3.dirty = true; await g3Wait(1000); if (!ok()) return; }
  const win = DIR.score[0] === DIR.score[1] ? null : DIR.score[0] > DIR.score[1] ? A : B; ta.win = win === A; tb.win = win === B; DIR.round = null;
  if (win) { DIR.focusPt = win; await g3Fly({ tx: win.x - FR.w / 2, tz: win.y - FR.h / 2, dist: 2500, tilt: .72, az: azTwo + 1.1 }, { dur: 2600, arc: 500, ant: 0, dip: 0 }); if (!ok()) return; }
  g3Title(win ? `<span class="seal"><span>胜</span></span><b>${cname(win)}</b><span>${DIR.score[0]} : ${DIR.score[1]}</span>` : `<b>${ZH("平局", "Draw")}</b><span>${DIR.score[0]} : ${DIR.score[1]}</span>`, 2400, "big win"); snd("win");
  await g3Wait(2600); if (!ok()) return; if (DIR.scene === "duel") { DIR.scene = null; g3Cine(false); } return true; }
/* ---------- scene: Su Shi's life as one tracking shot ---------- */
function g3SuBuild() { const T = G3.T; if (DIR.su) { DIR.su.mesh.visible = true; return DIR.su; }
  const stops = SU.map(([y, id, zh, en]) => ({ y, c: BYID.get(id), zh, en })).filter(s => s.c), pts = []; stops.forEach((s, i) => { if (!i || s.c !== stops[i - 1].c) pts.push(new T.Vector3(s.c.x - FR.w / 2, 0, s.c.y - FR.h / 2)); });
  const curve = new T.CatmullRomCurve3(pts, false, "centripetal", .5), N = 800, samp = curve.getSpacedPoints(N), ex = G3.k; for (const p of samp) p.y = g3H(p.x + FR.w / 2, p.z + FR.h / 2) * ex + 16;
  const tube = new T.TubeGeometry(new T.CatmullRomCurve3(samp), N, 7, 6, false), mesh = new T.Mesh(tube, new T.MeshBasicMaterial({ color: 0xb23a2b, fog: false })); tube.setDrawRange(0, 0); G3.scene.add(mesh);
  let from = 0; const us = stops.map(s => { let bi = from, bd = 1e12; for (let i = from; i < samp.length; i++) { const d = (samp[i].x - (s.c.x - FR.w / 2)) ** 2 + (samp[i].z - (s.c.y - FR.h / 2)) ** 2; if (d < bd) { bd = d; bi = i; } if (d < 25 && i > from) break; } from = bi; return bi / N; });
  let km = 0; for (let i = 1; i < samp.length; i++) km += Math.hypot(samp[i].x - samp[i - 1].x, samp[i].z - samp[i - 1].z);
  return DIR.su = { stops, us, tube, mesh, N, km, shown: -1, anim: null }; }
function g3SuDraw(u) { const s = DIR.su; s.tube.setDrawRange(0, Math.floor(u * s.N) * 36); G3.dirty = true; }
async function g3Su(tok) { tok = tok ?? (g3Cut(), DIR.seq); const ok = () => tok === DIR.seq; DIR.scene = "su"; g3Cine(true); G3.sel = null; G3.ring.visible = false; g3Card(); g3TowersClear(); g3ModeQuick("terrain");
  const s = g3SuBuild(); g3SuDraw(0); s.shown = -1; const first = s.stops[0].c;
  g3Title(`<small>${ZH("古今同图", "THEN & NOW")}</small><b>${ZH("苏轼一生的行迹", "The travels of Su Shi")}</b><span>1037–1101 · ${s.stops.length} ${ZH("站", "stops")}</span>`, 2500, "big");
  DIR.focusPt = first; await g3Fly({ tx: first.x - FR.w / 2, tz: first.y - FR.h / 2, dist: 2100, tilt: 1.0 }, { wipe: true, dur: 2600 }); if (!ok()) return; s.shown = 0; snd("stamp");
  g3Title(`<small>${s.stops[0].y}</small><b>${cname(first)}</b><span>${ZH(s.stops[0].zh, s.stops[0].en)}</span>`, 1200, "stop"); await g3Wait(900); if (!ok()) return;
  for (let i = 1; i < s.stops.length; i++) { const a = s.stops[i - 1].c, st = s.stops[i], b = st.c, dx = b.x - a.x, dz = b.y - a.y, L = Math.hypot(dx, dz), dur = clamp(650 + L * .8, 750, 1900);
    const az = L > 30 ? G3.cam.az + clamp(g3Ang(Math.atan2(-dx, -dz) - G3.cam.az), -.6, .6) * .35 : G3.cam.az;
    s.anim = { u0: s.us[i - 1], u1: s.us[i], t0: performance.now(), dur }; DIR.focusPt = b;
    await g3Fly({ tx: b.x - FR.w / 2, tz: b.y - FR.h / 2, dist: clamp(1400 + L * .8, 1700, 3200), tilt: 1.0, az }, { dur, arc: Math.min(L * .25, 420), ant: 0, dip: 0 }); if (!ok()) return;
    s.shown = i; snd("stamp"); g3Title(`<small>${st.y}</small><b>${cname(b)}</b><span>${ZH(st.zh, st.en)}</span>`, 1050, "stop"); await g3Wait(620); if (!ok()) return; }
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const t of s.stops) { x0 = Math.min(x0, t.c.x); y0 = Math.min(y0, t.c.y); x1 = Math.max(x1, t.c.x); y1 = Math.max(y1, t.c.y); }
  DIR.focusPt = null; await g3Fly({ tx: (x0 + x1) / 2 - FR.w / 2, tz: (y0 + y1) / 2 - FR.h / 2 + 150, dist: Math.max(x1 - x0, (y1 - y0) * 1.4) * 1.3 + 900, tilt: .85, az: -.08 }, { dur: 2600, arc: 0, ant: 0, dip: 0 }); if (!ok()) return;
  g3Title(`<b>${ZH(`一生辗转约 ${(Math.round(s.km / 100) * 100).toLocaleString("en-US")} 公里`, `About ${(Math.round(s.km / 100) * 100).toLocaleString("en-US")} km in one life`)}</b><span>${ZH("示意路线 · 正式版取自中国历代人物传记资料库（CBDB）", "Illustrative route · production data from CBDB")}</span>`, 2800, "big");
  await g3Wait(3000); if (!ok()) return; if (DIR.scene === "su") { DIR.scene = null; g3Cine(false); } return true; }
/* ---------- scene: the opening ---------- */
async function g3OpeningCine() { const h = g3Home(); G3.sel = null; G3.ring.visible = false; g3Card(); g3TowersClear(); if (DIR.su) DIR.su.mesh.visible = false;
  Object.assign(G3.cam, { ...h, dist: Math.min(12500, h.dist * 1.9), tilt: .3, az: h.az + .55 }); G3.ex = 0; G3.cloudA = 0; g3Apply();
  if (!RM()) { const d = 3800; DIR.wipe = { t0: performance.now() - d * .5, dur: d }; }
  setTimeout(() => g3Title(`<b class="brush">${ZH("江山图鉴", "Jiangshan Atlas")}</b><span>${ZH("千里江山，一城一印", "Every city, a seal of its own")}</span>`, 2600, "big"), RM() ? 0 : 1000);
  await g3Fly({ ...h }, { dur: 4400, arc: 0, ant: 0, dip: 0, extra: { ex: G3.mode === "terrain" ? 1 : .02, cloudA: 1 } }); }
/* ---------- the continuous take ---------- */
async function g3Trailer() { g3Cut(); const tok = DIR.seq, ok = () => tok === DIR.seq; DIR.scene = "trailer"; g3Cine(true); g3ModeQuick("terrain");
  await g3OpeningCine(); if (!ok()) return; await g3Wait(500); if (!ok()) return;
  const home = BYID.get(M.home || V4.home || "511300") || BYID.get("511300"); g3Cine(true);
  await g3Fly2City(home.id); if (!ok()) return; await g3Wait(2600); if (!ok()) return;
  const sib = mSibs(home).filter(x => x.id !== home.id).sort((a, b) => Math.hypot(a.x - home.x, a.y - home.y) - Math.hypot(b.x - home.x, b.y - home.y))[0];
  if (sib) { await g3Fly2City(sib.id, { track: true }); if (!ok()) return; await g3Wait(2000); if (!ok()) return; }
  const [ra, rb] = g3PkPair(home); await g3Duel(ra.id, rb.id, tok); if (!ok()) return; g3Cine(true); await g3Wait(400); g3TowersClear();
  await g3Su(tok); if (!ok()) return; g3Cine(true); DIR.su.mesh.visible = false; DIR.scene = "trailer";
  g3Title(`<small>${ZH("换个角度看", "ANOTHER VIEW")}</small><b>${ZH("人口，从土地里长出来", "Population, rising from the land")}</b>`, 2600, "big"); g3SetMode("pop"); await g3Wait(4200); if (!ok()) return;
  g3SetMode("terrain"); await g3Wait(1500); if (!ok()) return;
  await g3Fly(g3Home(), { wipe: true, dur: 3000 }); if (!ok()) return;
  g3Title(`<b class="brush">${ZH("你的家乡，在哪儿？", "Where are you from?")}</b><span>${ZH("点一座城，飞过去", "Tap a city to fly there")}</span>`, 3200, "big"); await g3Wait(3200); if (ok()) { DIR.scene = null; g3Cine(false); } }
/* ---------- overlay for scenes: card leader line, tower labels, route seals ---------- */
function g3OverlayDir() { const ov = G3.ov, ctx = ov.getContext("2d"), u = G3.u, OW = ov.width, OH = ov.height, cam = G3.camera, v = new G3.T.Vector3();
  const proj = (x, y, z) => { v.set(x, y, z); v.project(cam); if (v.z > 1 || v.x < -1.2 || v.x > 1.2 || v.y < -1.2 || v.y > 1.2) return null; return [(v.x + 1) / 2 * OW, (1 - v.y) / 2 * OH]; };
  if (G3.cardA && G3.sel && G3.dev !== "phone") { const [sx, sy, L, T_, W] = G3.cardA, ex = (L > sx ? L : L + W) * u, ey = (T_ + 48) * u; ctx.save(); ctx.strokeStyle = "rgba(43,35,29,.6)"; ctx.lineWidth = 1.2 * u; ctx.setLineDash([5 * u, 4 * u]); ctx.beginPath(); ctx.moveTo(sx * u, sy * u); ctx.quadraticCurveTo((sx * u + ex) / 2, Math.min(sy * u, ey) - 30 * u, ex, ey); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = "#b23a2b"; ctx.beginPath(); ctx.arc(sx * u, sy * u, 3.2 * u, 0, 7); ctx.fill(); ctx.restore(); }
  if (DIR.towers) DIR.towers.forEach((t, i) => { const q = proj(t.g.position.x, t.base + t.h + 56, t.g.position.z); if (!q) return; const r = DIR.round, show = r && (i ? r.showB : r.showA), val = show ? r.f(i ? r.vb : r.va) : "";
    ctx.save(); ctx.textAlign = "center"; ctx.font = `700 ${17 * u}px "Noto Serif SC", serif`; const nm = cname(t.c) + (t.win ? " ★" : ""), w1 = ctx.measureText(nm).width; ctx.font = `600 ${14 * u}px "Noto Serif SC", serif`; const w2 = ctx.measureText(val).width, w = Math.max(w1, w2) + 26 * u, h = (val ? 50 : 30) * u;
    ctx.fillStyle = t.color; ctx.shadowColor = "rgba(0,0,0,.35)"; ctx.shadowBlur = 10 * u; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(q[0] - w / 2, q[1] - h, w, h, 6 * u) : ctx.rect(q[0] - w / 2, q[1] - h, w, h); ctx.fill(); ctx.shadowBlur = 0;
    ctx.fillStyle = "#fbf4e6"; ctx.textBaseline = "top"; ctx.font = `700 ${17 * u}px "Noto Serif SC", serif`; ctx.fillText(nm, q[0], q[1] - h + 7 * u); if (val) { ctx.font = `600 ${14 * u}px "Noto Serif SC", serif`; ctx.fillStyle = "#f3d58a"; ctx.fillText(val, q[0], q[1] - h + 29 * u); } ctx.restore(); });
  if (DIR.su && DIR.su.mesh.visible) { const s = DIR.su; for (let i = 0; i <= s.shown && i < s.stops.length; i++) { const st = s.stops[i], q = proj(st.c.x - FR.w / 2, g3H(st.c.x, st.c.y) * G3.k + 18, st.c.y - FR.h / 2); if (!q) continue; const cur = i === s.shown, z = (cur ? 11 : 7) * u;
      ctx.save(); ctx.fillStyle = "#b23a2b"; ctx.strokeStyle = "#fbf4e6"; ctx.lineWidth = 1.5 * u; ctx.fillRect(q[0] - z / 2, q[1] - z / 2, z, z); ctx.strokeRect(q[0] - z / 2, q[1] - z / 2, z, z);
      ctx.font = `600 ${(cur ? 13 : 11) * u}px "Noto Serif SC", serif`; ctx.textAlign = "left"; ctx.textBaseline = "middle"; haloText(ctx, `${st.y} ${cname(st.c)}`, q[0] + z, q[1], "#2b231d", "rgba(246,239,224,.92)", 3 * u); ctx.restore(); } } }
