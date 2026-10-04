// Limn plot - the web UI. The server (plot/server.py) does the slicing; this
// draws the bed, lets you place and paint drawings, and shows the G-code back.
// World coordinates are bed mm, y up: #world flips them.
'use strict';

const NS = 'http://www.w3.org/2000/svg';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(+v)) ? '' : String(+(+v).toFixed(d));
const store = {
  get(k, d) { try { const v = localStorage.getItem('limn-plot:' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('limn-plot:' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

let S = null;                   // the server's state
let sel = store.get('sel', null);
let view = store.get('view', 'tools');
let paintTo = null;             // tool id | 'mask' | 'skip' | 'reset'
let paintTarget = 'both';
let paintScope = 'shape';
const geo = {};                 // object id -> {sig, data}
let preview = null;
let gcodeLines = null;
let vb = null;                  // viewBox, svg user units (x, -y)
const openOpts = new Set();     // colour rows with their options open
const hiddenObjs = new Set(store.get('hiddenObjs', []));   // drawings not shown (they still plot)
function setHidden(id, hide) {
  hide ? hiddenObjs.add(id) : hiddenObjs.delete(id);
  store.set('hiddenObjs', [...hiddenObjs]);
  renderObjectList(); renderObjects();
}

// --- server ---------------------------------------------------------------
async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* not json */ }
    toast(msg, true);
    throw new Error(msg);
  }
  const type = r.headers.get('content-type') || '';
  return type.includes('json') ? r.json() : r.text();
}

// Instead of confirm(): a button acts only when pressed twice within 2 s. The first press turns it yellow
// (.armed) and says what the second will do; nothing happens on one stray click, and no dialog is in the way.
// Remembered by `key`, not by the element: a panel the printer poll redraws keeps the second press working.
const armedAt = {};
function twice(key, btn, what) {
  const now = Date.now();
  if (armedAt[key] && now - armedAt[key] < 2000) {
    delete armedAt[key];
    for (const b of $$('.armed')) b.classList.remove('armed');
    return true;
  }
  armedAt[key] = now;
  if (btn) {
    btn.classList.add('armed');
    setTimeout(() => { if (!armedAt[key] || Date.now() - armedAt[key] >= 2000) btn.classList.remove('armed'); }, 2050);
  }
  toast(`${what}: press again to do it`);
  return false;
}

let toastTimer = null;
function toast(msg, bad = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (bad ? ' bad' : '');
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 3000);
}

// Panels are redrawn whole. A redraw the printer poll brings (not something done
// here) waits while you are in that panel: it would close an open select, drop a
// half-typed value or end a drag. It comes once you leave the panel.
let background = false;
const later = new Map();        // panel -> the html it waits to show
const busyIn = (el) => el.contains(document.activeElement) || !!(numDrag && el.contains(numDrag.input));
function fill(el, html) {
  if (background) {
    if (el._html === html) return;
    if (busyIn(el)) { later.set(el, html); return; }
  }
  later.delete(el);
  el.innerHTML = html;
  el._html = html;
  helpify(el);
}

// Tooltips for the fields the panels draw: by data-k / data-f / data-pf / data-p / id
const HELP = {
  z_touch: 'G-code z where a pen whose tag is right first touches the paper; pen-down is this less the pen\'s press',
  z_min: 'The lowest z anything goes to (Klipper\'s limit less a tag\'s dz)',
  z_max: 'The highest z anything goes to',
  z_travel: 'Height of long travels over the paper',
  hop_distance: 'Travels shorter than this (mm) only hop the pen\'s lift; longer ones go up to z travel',
  clearance: 'mm over a zone or an object that a travel crosses',
  feed_travel: 'Speed of travels, mm/min',
  order_time: 's spent improving the order of the strokes (shorter travels)',
  width: 'The line it leaves, mm: fills are spaced by it',
  press: 'mm past first touch while drawing (z touch less this is pen-down); fineliners 0.15, felt tips 0.3',
  press_max: 'Never pressed more than this, whatever a job asks: fineliners are delicate',
  overlap: 'How much of its width neighbouring fill lines share',
  feed: 'Drawing speed, mm/min',
  z_down: 'Pen-down over the surface, for a tool without a press',
  hop: 'Lift over pen-down between strokes, for a tool without a press',
  link: 'Stays down across gaps up to this (mm); empty: half its width',
  plunge_feed: 'Speed coming down onto the paper, mm/min',
  wear: 'A pencil goes this much lower per metre drawn',
  focus: 'A laser\'s height over the surface',
  power: 'Laser power, 0-255',
  reload_every: 'A brush goes back to its well every this many mm',
  well_z: 'Brush height in the well',
  bleed: 'mm kept clear around what another tool (or a mask) draws on top: inks that run don\'t meet',
  layers: 'Light under dark: a lighter ink isn\'t cut out where a darker one draws over it, it is drawn whole and the light pens plot first, so the dark outlines over them stay crisp. Cut out: each ink only where it shows',
  small: 'Shapes too small or dense for the tool\'s line (it would fill them in: tiny handwriting, text): leave them out, draw them with a warning, or just draw them',
  dry: 'Minutes it may stay out of its cap in the machine before the dock goes red and beeps (twice that while printing)',
  webcam: 'The camera\'s name in Moonraker\'s webcams',
  focus_z: 'Camera: the G-code z where what lies on the bed is sharpest',
  fov: 'Camera: mm across and down one shot, at its focus height',
  'f-x': 'Where the drawing\'s corner goes, mm along X (drag sideways to change)',
  'f-y': 'Where the drawing\'s corner goes, mm along Y (drag sideways to change)',
  'f-r': 'Turn, degrees about its corner',
  'f-s': 'Size, % of the SVG\'s own',
  'f-occ': 'Shapes on top hide what is under them, as the SVG shows it',
  to: 'The tool this colour is drawn with; mask: it hides what is under it; skip: not drawn',
  fill: 'How insides are filled: lines one way, both ways, rings following the outline, or not at all',
  angle: 'Fill lines\' angle, degrees',
  border: 'Draw the outline around a fill too',
  spacing: 'mm between fill lines; empty: from the tool\'s width and overlap',
  stroke: 'Outlines: a line down the middle, or as wide as the SVG has them',
  mode: 'This text in its own font (uploaded), a single-line font, or not at all',
  line_font: 'The single-line font it is drawn in',
  font: 'The uploaded font it is drawn in; by family: the one matching the SVG',
  'm-bed': 'The bed on the plotter: its paper is the draw area',
  'm-follow': 'Take the bed from Klipper as it changes',
  key: 'The pen type\'s key, on the tags: up to 8 of a-z 0-9 - _ . , never renamed',
  name: 'Its name', short: 'How tags name it, with the colour: up to 20 characters',
  kind: 'What sort of tool: pen, pencil, brush, laser, camera',
};
function helpify(root) {
  for (const el of root.querySelectorAll('input, select, button, label')) {
    if (el.title) continue;
    const k = el.dataset.k || el.dataset.dk || el.dataset.f || el.dataset.pf || el.dataset.p || el.id;
    if (k && HELP[k]) el.title = HELP[k];
  }
}
function flushLater() {
  for (const [el, html] of later) if (!busyIn(el)) { later.delete(el); el.innerHTML = html; el._html = html; }
}
document.addEventListener('focusout', () => setTimeout(flushLater, 0));
function quietly(fn) { background = true; try { fn(); } finally { background = false; } }

function setState(s, { slice = true, quiet = false } = {}) {
  S = s;
  if (sel && !S.job.objects.some((o) => o.id === sel)) sel = null;
  if (!sel && S.job.objects.length) sel = S.job.objects[0].id;
  store.set('sel', sel);
  quiet ? quietly(render) : render();
  if (slice) scheduleSlice();
}

const obj = (id) => S.job.objects.find((o) => o.id === id);
const info = (id) => S.objects[id];

// --- slicing ----------------------------------------------------------------
let sliceTimer = null, slicing = false, again = false;
function scheduleSlice(delay = 200) {
  clearTimeout(sliceTimer);
  $('#paths-layer').classList.add('stale');
  sliceTimer = setTimeout(runSlice, delay);
}
async function runSlice() {
  if (slicing) { again = true; return; }
  if (!S.job.objects.length) { preview = null; renderPreview(); renderOutput(); status('empty bed'); return; }
  slicing = true;
  status('slicing…', true);
  try {
    preview = await api('POST', '/api/slice');
    gcodeLines = null;
    markSmall();
    renderPreview();
    renderOutput();
    status(`${preview.lines} lines · ${preview.ms} ms`);
  } catch (e) {
    status('slice failed');
  } finally {
    slicing = false;
    if (again) { again = false; runSlice(); }
  }
}
function status(text, busy = false) {
  const s = $('#slice-status');
  s.textContent = text;
  s.classList.toggle('busy', busy);
}

// --- canvas: view box, pan, zoom -------------------------------------------
const svg = $('#canvas');
const world = $('#world');

function extent() {
  const m = S.machine;
  const [tx0, ty0, tx1, ty1] = m.travel_area;
  return [Math.min(0, tx0), Math.min(0, ty0), Math.max(m.bed[0], tx1), Math.max(m.bed[1], ty1)];
}
// The canvas fills the page; panels float over it. Fitting puts what is fitted in the
// space between them: --dock-l, --dock-r, --top (panels.js), the rulers, the scrubber.
function freeArea() {
  const r = svg.getBoundingClientRect(), cs = getComputedStyle(document.documentElement);
  const v = (k, d) => parseFloat(cs.getPropertyValue(k)) || d;
  const ruler = parseFloat(getComputedStyle($('#stage')).getPropertyValue('--ruler')) || 20;
  return { r, l: v('--dock-l', 0) + ruler + 14, rt: v('--dock-r', 0) + 14, t: v('--top', 0) + ruler + 14, b: 64 };
}
function fitTo(x0, y0, x1, y1) {
  const { r, l, rt, t, b } = freeArea();
  const fw = Math.max(r.width - l - rt, 80), fh = Math.max(r.height - t - b, 80);
  const k = Math.max((x1 - x0) / fw, (y1 - y0) / fh);              // mm a pixel
  vb = { x: x0 - (l + (fw - (x1 - x0) / k) / 2) * k, y: -y1 - (t + (fh - (y1 - y0) / k) / 2) * k, w: r.width * k, h: r.height * k };
  applyVb();
}
function fit() {
  const [x0, y0, x1, y1] = extent();
  fitTo(x0 - 4, y0 - 4, x1 + 4, y1 + 4);
}
function applyVb() {
  svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  requestAnimationFrame(() => { drawRulers(); drawHandles(); if (typeof drawHead === 'function') drawHead(); });
}
function userPt(e) {
  const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
  return p.matrixTransform(svg.getScreenCTM().inverse());
}
function worldPt(e) {
  const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
  return p.matrixTransform(world.getScreenCTM().inverse());
}
function zoom(k, at) {
  const c = at || { x: vb.x + vb.w / 2, y: vb.y + vb.h / 2 };
  vb = { x: c.x - (c.x - vb.x) * k, y: c.y - (c.y - vb.y) * k, w: vb.w * k, h: vb.h * k };
  applyVb();
}
// A mouse wheel zooms. A trackpad: two fingers pan, a pinch zooms (the browser sends
// it as a wheel with ctrlKey; Safari as gesture events). They differ in their deltas:
// a wheel steps in lines, or in whole notches of 50 px or more, and never sideways.
let trackpadUntil = 0;              // a swipe's momentum goes on in big steps: still the trackpad
function isWheel(e) {
  if (Date.now() < trackpadUntil) return false;
  const notch = e.deltaMode !== 0 || (e.deltaX === 0 && Math.abs(e.deltaY) >= 50 && Number.isInteger(e.deltaY));
  if (!notch) trackpadUntil = Date.now() + 400;
  return notch;
}
function panBy(dx, dy) {
  const r = svg.getBoundingClientRect(), k = Math.max(vb.w / r.width, vb.h / r.height);
  vb = { ...vb, x: vb.x + dx * k, y: vb.y + dy * k };
  applyVb();
}
svg.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (e.ctrlKey) return zoom(Math.exp(e.deltaY * 0.01), userPt(e));                 // a pinch (or Ctrl+wheel)
  if (isWheel(e)) return zoom(Math.exp(e.deltaY * 0.0015), userPt(e));
  const px = e.deltaMode === 1 ? 16 : 1;
  panBy(e.deltaX * px, e.deltaY * px);
}, { passive: false });
let gestureScale = 1;               // Safari: a pinch comes as gesture events
svg.addEventListener('gesturestart', (e) => { e.preventDefault(); gestureScale = 1; });
svg.addEventListener('gesturechange', (e) => {
  e.preventDefault();
  zoom(gestureScale / e.scale, userPt(e));
  gestureScale = e.scale;
});
svg.addEventListener('contextmenu', (e) => e.preventDefault());       // the right button pans

// Two fingers on a touch screen: pinch to zoom, move to pan (before anything else
// takes the pointer: a second finger ends what the first one started)
const touches = new Map();
let pinch = null;
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
svg.addEventListener('pointerdown', (e) => {
  if (e.pointerType !== 'touch') return;
  touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (touches.size !== 2) return;
  const [a, b] = [...touches.values()];
  pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, m: mid(a, b), vb: { ...vb } };
  drag = null;
  if (typeof sdrag !== 'undefined') sdrag = null;
  svg.classList.remove('panning');
  e.stopImmediatePropagation();
}, true);
svg.addEventListener('pointermove', (e) => {
  if (!touches.has(e.pointerId)) return;
  touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (!pinch || touches.size !== 2) return;
  e.stopImmediatePropagation();
  const [a, b] = [...touches.values()], m = mid(a, b), r = svg.getBoundingClientRect();
  const s0 = pinch.vb.w / r.width, s1 = s0 * pinch.d / (Math.hypot(a.x - b.x, a.y - b.y) || 1);
  const ux = pinch.vb.x + (pinch.m.x - r.left) * s0, uy = pinch.vb.y + (pinch.m.y - r.top) * s0;    // under the fingers at the start
  vb = { x: ux - (m.x - r.left) * s1, y: uy - (m.y - r.top) * s1, w: r.width * s1, h: r.height * s1 };
  applyVb();
}, true);
for (const type of ['pointerup', 'pointercancel']) {
  svg.addEventListener(type, (e) => {
    touches.delete(e.pointerId);
    if (touches.size < 2 && pinch) { pinch = null; e.stopImmediatePropagation(); }
  }, true);
}

let spaceDown = false;
let mode = 'select';    // select | pan | paint | mask
let maskSel = null;     // {id, i}: a masked region picked with the mask tool
let drag = null;        // {kind: 'pan'|'move'|'scale'|'rotate', ...}

const rad = (d) => d * Math.PI / 180;
function rot(p, deg) {
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg));
  return { x: c * p.x - s * p.y, y: s * p.x + c * p.y };
}
function toWorld(pl, p) { const r = rot(p, pl.rotate); return { x: pl.x + r.x, y: pl.y + r.y }; }
function toLocal(pl, w) { return rot({ x: w.x - pl.x, y: w.y - pl.y }, -pl.rotate); }
const mmPerPx = () => 1 / world.getScreenCTM().a;

function setMode(m) {
  mode = m;
  if (m !== 'paint') paintTo = null;
  else if (!paintTo) paintTo = (Object.values(S.tools).find((t) => t.draws !== false) || {}).id;
  if (m !== 'mask') maskSel = null;
  $$('#rail [data-mode]').forEach((b) => b.classList.toggle('on', b.dataset.mode === m));
  svg.classList.toggle('pan-mode', m === 'pan');
  svg.classList.toggle('mask-mode', m === 'mask');
  renderObjects();
  renderPalette();
  drawHandles();
}

// The shape under the pointer, or the nearest within PICK px: a stroke is drawn as
// wide as its SVG has it, often under a pixel, and only what is painted takes a click.
// So when nothing is right under it, every shape is asked again with an invisible
// stroke 2 PICK px wide (.picking, never painted: it is gone before the next frame).
// Never through a panel lying over the canvas.
const PICK = 6;
function pickShape(e) {
  const layer = $('#design-layer');
  const at = () => {
    const stack = document.elementsFromPoint(e.clientX, e.clientY);
    if (!stack.length || !svg.contains(stack[0])) return null;
    return stack.find((el) => el.matches('#design-layer path.shape')) || null;
  };
  let el = at();
  if (!el) {
    layer.style.setProperty('--pickw', `${2 * PICK}px`);
    layer.classList.add('picking');
    el = at();
    layer.classList.remove('picking');
  }
  return el;
}
let hot = null, hoverAt = null;
function setHot(el) {
  if (hot === el) return;
  if (hot) hot.classList.remove('hot');
  hot = el;
  if (hot) hot.classList.add('hot');
}

svg.addEventListener('pointerdown', (e) => {
  if (mode === 'mask' && e.button === 0 && !spaceDown) {
    const m = e.target.closest('.objmask');
    if (m) {
      maskSel = { id: m.closest('g.obj').dataset.id, i: +m.dataset.m };
      sel = maskSel.id; store.set('sel', sel); render();
      return;
    }
    const g = e.target.closest('g.obj');
    const id = sel || (g && g.dataset.id);
    if (!id) return flash('Select a drawing first, then drag over the part of it not to draw');
    maskSel = null;
    drag = { kind: 'mask', id, start: worldPt(e), at: worldPt(e) };
    try { svg.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ }
    return;
  }
  const handle = e.target.closest('[data-handle]');
  const picking = mode === 'paint' && paintTo && e.button === 0 && !spaceDown;
  const shape = picking ? pickShape(e) : e.target.closest('path.shape');
  const g = shape ? shape.closest('g.obj') : e.target.closest('g.obj');
  if (picking) {
    if (shape) paintShape(g.dataset.id, +shape.dataset.i, e.shiftKey ? 'colour' : paintScope);
    else flash('No shape here: click on a line or inside a filled shape');
    if (shape || g) return;
  }
  const capture = () => { try { svg.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ } };
  if (e.button === 1 || e.button === 2 || spaceDown || mode === 'pan' || (e.button === 0 && !g && !handle)) {
    // Empty canvas: pan; a click without moving deselects
    drag = { kind: 'pan', cx: e.clientX, cy: e.clientY, vb: { ...vb }, click: e.button === 0 && !g && !handle && mode === 'select' };
    svg.classList.add('panning');
    capture();
    return;
  }
  if (e.button !== 0) return;
  if (handle && sel) {
    const o = obj(sel), [w, h] = info(sel).size;
    const kind = handle.dataset.handle;
    if (kind === 'rotate') {
      const c = { x: w / 2, y: h / 2 };
      const wc = toWorld(o.placement, c);
      const p = worldPt(e);
      drag = { kind: 'rotate', id: sel, p: { ...o.placement }, c, wc, a0: Math.atan2(p.y - wc.y, p.x - wc.x) };
    } else {
      const k = +kind;      // corner 0..3: (0,0) (w,0) (w,h) (0,h)
      const corners = [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }];
      drag = { kind: 'scale', id: sel, p: { ...o.placement }, corner: corners[k], anchor: corners[(k + 2) % 4],
               centre: { x: w / 2, y: h / 2 }, size: [w, h], scale: o.scale, k: 1 };
    }
    capture();
    return;
  }
  if (!g) return;
  const id = g.dataset.id;
  if (sel !== id) { sel = id; store.set('sel', sel); render(); }
  const o = obj(id);
  drag = { kind: 'move', id, start: worldPt(e), p: { ...o.placement }, moved: false };
  capture();
});

svg.addEventListener('pointermove', (e) => {
  const w = worldPt(e);
  cursor = w;
  drawRulers();
  if (!drag && mode === 'paint' && paintTo) {
    if (!hoverAt) requestAnimationFrame(() => { setHot(pickShape(hoverAt)); hoverAt = null; });
    hoverAt = { clientX: e.clientX, clientY: e.clientY };
  } else setHot(null);
  if (!drag) return;
  if (drag.kind === 'pan') {
    const r = svg.getBoundingClientRect();
    const s = Math.max(drag.vb.w / r.width, drag.vb.h / r.height);
    if (Math.abs(e.clientX - drag.cx) + Math.abs(e.clientY - drag.cy) > 3) drag.click = false;
    vb = { ...drag.vb, x: drag.vb.x - (e.clientX - drag.cx) * s, y: drag.vb.y - (e.clientY - drag.cy) * s };
    applyVb();
    return;
  }
  if (drag.kind === 'mask') {
    drag.at = w;
    const L = $('#overlay-layer');
    L.innerHTML = '';
    const [a, b] = [drag.start, w];
    svgEl('rect', { class: 'mask-draft', x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) }, L);
    hint(`${num(Math.abs(a.x - b.x), 1)} × ${num(Math.abs(a.y - b.y), 1)} mm not drawn`);
    return;
  }
  const o = obj(drag.id);
  drag.moved = true;
  $('#paths-layer').classList.add('stale');
  if (drag.kind === 'move') {
    o.placement = { ...drag.p, x: +(drag.p.x + w.x - drag.start.x).toFixed(2), y: +(drag.p.y + w.y - drag.start.y).toFixed(2) };
    placeObject(o);
    hint(`x ${num(o.placement.x, 1)}  y ${num(o.placement.y, 1)}`);
  } else if (drag.kind === 'rotate') {
    let a = drag.p.rotate + (Math.atan2(w.y - drag.wc.y, w.x - drag.wc.x) - drag.a0) * 180 / Math.PI;
    a = ((e.shiftKey ? Math.round(a / 15) * 15 : Math.round(a * 10) / 10) % 360 + 360) % 360;
    const r = rot(drag.c, a);
    o.placement = { x: +(drag.wc.x - r.x).toFixed(3), y: +(drag.wc.y - r.y).toFixed(3), rotate: a };
    placeObject(o);
    hint(`${num(a, 1)}°`);
  } else if (drag.kind === 'scale') {
    const anchor = e.altKey ? drag.centre : drag.anchor;
    const L = toLocal(drag.p, w);
    const dx = drag.corner.x - anchor.x, dy = drag.corner.y - anchor.y;
    const k = Math.max(0.02, ((L.x - anchor.x) * dx + (L.y - anchor.y) * dy) / (dx * dx + dy * dy));
    const wa = toWorld(drag.p, anchor);
    const r = rot({ x: anchor.x * k, y: anchor.y * k }, drag.p.rotate);
    o.placement = { ...drag.p, x: +(wa.x - r.x).toFixed(3), y: +(wa.y - r.y).toFixed(3) };
    drag.k = k;
    placeObject(o, k);
    hint(`${num(drag.size[0] * k, 1)} × ${num(drag.size[1] * k, 1)} mm · ${num(drag.scale * k * 100, 1)} %`);
  }
  drawHandles();
  const fx = $('#f-x'), fy = $('#f-y'), fr = $('#f-r');
  if (fx) { fx.value = num(o.placement.x); fy.value = num(o.placement.y); fr.value = num(o.placement.rotate); }
});

svg.addEventListener('pointerup', async () => {
  const d = drag; drag = null;
  svg.classList.remove('panning');
  hint('');
  if (!d) return;
  if (d.kind === 'pan') {
    if (d.click && sel) { sel = null; store.set('sel', sel); render(); }
    return;
  }
  if (d.kind === 'mask') {
    $('#overlay-layer').innerHTML = '';
    const o = obj(d.id), [a, b] = [d.start, d.at];
    if (!o || Math.abs(a.x - b.x) < 0.3 || Math.abs(a.y - b.y) < 0.3) return;
    // the rectangle's corners, in the drawing's own mm (scale 1), as the slicer has its shapes
    const poly = [[a.x, a.y], [b.x, a.y], [b.x, b.y], [a.x, b.y]].map(([x, y]) => {
      const l = toLocal(o.placement, { x, y });
      return [+(l.x / o.scale).toFixed(3), +(l.y / o.scale).toFixed(3)];
    });
    maskSel = { id: o.id, i: (o.masks || []).length };
    return patchObj(o.id, { masks: [...(o.masks || []), poly] });
  }
  if (!d.moved) return;
  const o = obj(d.id);
  const body = { placement: o.placement };
  if (d.kind === 'scale') body.scale = +(d.scale * d.k).toFixed(5);
  setState(await api('PATCH', `/api/objects/${d.id}`, body));
});

let flashUntil = 0;
function flash(text, ms = 2500) {
  flashUntil = Date.now() + ms;
  $('#hint').textContent = text;
  setTimeout(() => { if (Date.now() >= flashUntil) hint(''); }, ms);
}
function hint(text) {
  if (!text && Date.now() < flashUntil) return;     // a flash() stays its while
  $('#hint').textContent = text || (mode === 'paint' && paintTo
    ? `Painting ${paintTo} · ${paintTarget} · ${paintScope} (shift: whole colour) · Esc to stop`
    : mode === 'mask' ? 'Mask: drag where the drawing isn\'t drawn · Del removes a picked one' : '');
}

// The selected object's frame: corners scale (alt: about the middle), the knob turns (shift: 15°)
function drawHandles() {
  const L = $('#overlay-layer');
  L.innerHTML = '';
  const o = sel && obj(sel);
  if (!o || !info(o.id) || mode === 'paint' || mode === 'mask' || hiddenObjs.has(o.id)) return;
  const [w0, h0] = info(o.id).size;
  const k = drag && drag.kind === 'scale' && drag.id === o.id ? drag.k : 1;
  const w = w0 * k, h = h0 * k, pl = o.placement;
  const px = mmPerPx();
  const pts = [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }].map((p) => toWorld(pl, p));
  svgEl('polygon', { class: 'frame', points: pts.map((p) => `${p.x},${p.y}`).join(' ') }, L);
  const top = toWorld(pl, { x: w / 2, y: h }), knob = toWorld(pl, { x: w / 2, y: h + 18 * px });
  svgEl('line', { class: 'frame', x1: top.x, y1: top.y, x2: knob.x, y2: knob.y }, L);
  svgEl('circle', { class: 'handle rotate', 'data-handle': 'rotate', cx: knob.x, cy: knob.y, r: 5 * px }, L);
  const hs = 8 * px;
  pts.forEach((p, i) => {
    svgEl('rect', { class: 'handle', 'data-handle': i, x: p.x - hs / 2, y: p.y - hs / 2, width: hs, height: hs,
                    transform: `rotate(${pl.rotate} ${p.x} ${p.y})` }, L);
  });
}

// --- rulers --------------------------------------------------------------------
let cursor = null;
function drawRulers() {
  const ctm = world.getScreenCTM();
  if (!ctm || !S) return;
  const dpr = window.devicePixelRatio || 1;
  const style = getComputedStyle(document.documentElement);
  const ink = style.getPropertyValue('--muted').trim(), accent = style.getPropertyValue('--accent').trim();
  const pxmm = ctm.a;
  const step = [1, 2, 5, 10, 20, 50, 100].find((s) => s * pxmm >= 45) || 100;
  const minor = step / (step % 5 === 0 && step >= 5 ? 5 : 2);
  let ext = null;
  const o = sel && obj(sel);
  if (o && info(o.id)) {
    const [w, h] = info(o.id).size;
    const k = drag && drag.kind === 'scale' ? drag.k : 1;
    const c = [{ x: 0, y: 0 }, { x: w * k, y: 0 }, { x: w * k, y: h * k }, { x: 0, y: h * k }].map((p) => toWorld(o.placement, p));
    ext = [Math.min(...c.map((p) => p.x)), Math.min(...c.map((p) => p.y)), Math.max(...c.map((p) => p.x)), Math.max(...c.map((p) => p.y))];
  }
  for (const axis of ['x', 'y']) {
    const cv = $(axis === 'x' ? '#ruler-x' : '#ruler-y');
    const box = cv.getBoundingClientRect();          // the rulers sit between the panels
    const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext('2d');
    g.scale(dpr, dpr);
    g.clearRect(0, 0, W, H);
    g.font = '10px ui-monospace, monospace';
    g.fillStyle = ink; g.strokeStyle = ink; g.lineWidth = 1;
    // screen px of a world coordinate, relative to the ruler
    const at = axis === 'x' ? (v) => ctm.a * v + ctm.e - box.left : (v) => ctm.d * v + ctm.f - box.top;
    const len = axis === 'x' ? W : H;
    const lo = axis === 'x' ? (box.left - ctm.e) / ctm.a : (box.top + len - ctm.f) / ctm.d;
    const hi = axis === 'x' ? (box.left + len - ctm.e) / ctm.a : (box.top - ctm.f) / ctm.d;
    if (ext) {
      g.fillStyle = accent; g.globalAlpha = 0.18;
      const [a, b] = axis === 'x' ? [at(ext[0]), at(ext[2])] : [at(ext[3]), at(ext[1])];
      axis === 'x' ? g.fillRect(a, 0, b - a, H) : g.fillRect(0, a, W, b - a);
      g.globalAlpha = 1; g.fillStyle = ink;
    }
    for (let v = Math.floor(Math.min(lo, hi) / minor) * minor; v <= Math.max(lo, hi); v += minor) {
      const p = Math.round(at(v)) + 0.5;
      const major = Math.abs(v / step - Math.round(v / step)) < 1e-6;
      const t = major ? 9 : 4;
      g.beginPath();
      if (axis === 'x') { g.moveTo(p, H); g.lineTo(p, H - t); } else { g.moveTo(W, p); g.lineTo(W - t, p); }
      g.stroke();
      if (major) {
        if (axis === 'x') g.fillText(String(Math.round(v)), p + 2, 10);
        else { g.save(); g.translate(10, p - 2); g.rotate(-Math.PI / 2); g.fillText(String(Math.round(v)), 0, 0); g.restore(); }
      }
    }
    if (cursor) {
      const p = at(axis === 'x' ? cursor.x : cursor.y);
      g.strokeStyle = accent; g.beginPath();
      if (axis === 'x') { g.moveTo(p, 0); g.lineTo(p, H); } else { g.moveTo(0, p); g.lineTo(W, p); }
      g.stroke();
    }
  }
  $('#cursor').textContent = cursor ? `X ${num(cursor.x, 1)}  Y ${num(cursor.y, 1)}` : '';
}
svg.addEventListener('pointerleave', () => { cursor = null; drawRulers(); });
window.addEventListener('resize', () => { drawRulers(); drawHandles(); });

async function undo(redo = false) {
  const r = await api('POST', redo ? '/api/redo' : '/api/undo');
  if (!r.changed) toast(redo ? 'Nothing to redo' : 'Nothing to undo');
  setState(r.state);
}

// --- canvas: bed, objects, paths -------------------------------------------
function svgEl(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const rect = (r, cls, parent) => svgEl('rect', { x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1], class: cls }, parent);

let bedSig = null;
function renderBed() {
  const m = S.machine;
  const sig = JSON.stringify([m.bed, m.bed_art, m.draw_area, m.zones, $('#show-art').checked]);
  if (sig === bedSig) return;
  bedSig = sig;
  const L = $('#bed-layer');
  L.innerHTML = '';
  rect([0, 0, m.bed[0], m.bed[1]], 'bed-rect', L);
  if (m.bed_art && $('#show-art').checked) {
    svgEl('image', { href: '/api/bed-art', x: 0, y: -m.bed[1], width: m.bed[0], height: m.bed[1],
      transform: 'scale(1,-1)', preserveAspectRatio: 'none', opacity: 0.45 }, L);
  }
  for (const z of m.zones) {
    const r = rect(z.rect, 'zone ' + (z.z === null ? 'keep' : 'top'), L);
    svgEl('title', {}, r).textContent = z.name + (z.z === null ? ' (keep out)' : ` (top z ${z.z})`);
  }
  rect(m.draw_area, 'draw-area', L);
}

function effGroup(o, sh, part) {
  const colour = part === 'stroke' ? sh.stroke : sh.fill;
  if (!colour) return null;
  const over = (o.shapes[String(sh.i)] || {})[part];
  if (over) return over;
  const key = `${part} ${colour}`;
  if (o.groups[key]) return o.groups[key];
  const g = info(o.id).groups.find((x) => x.key === key);
  return g ? g.default : { tool: null, mask: false };
}

function paintOf(g) {
  // [colour, opacity] of a group in the Tools view
  if (!g) return ['none', 1];
  if (g.tool && S.tools[g.tool]) return [S.tools[g.tool].color, 1];
  if (g.mask) return ['var(--paper)', 1];
  return ['#999', 0.18];
}

function geoSig(o) {
  return JSON.stringify([o.svg, o.scale, o.tolerance, o.text, o.texts, S.fonts.map((f) => f.file)]);
}
async function ensureGeo(o) {
  const sig = geoSig(o);
  if (geo[o.id] && geo[o.id].sig === sig) return geo[o.id].data;
  const data = await api('GET', `/api/objects/${o.id}/shapes`);
  geo[o.id] = { sig, data };
  return data;
}

function placeObject(o, k = 1) {
  const g = $(`#design-layer g.obj[data-id="${CSS.escape(o.id)}"]`);
  if (g) g.setAttribute('transform', `translate(${o.placement.x} ${o.placement.y}) rotate(${o.placement.rotate})${k !== 1 ? ` scale(${k})` : ''}`);
}

let objRender = Promise.resolve();
function renderObjects() {
  objRender = objRender.then(drawObjects).catch((e) => console.error(e));
  return objRender;
}
async function drawObjects() {
  const L = $('#design-layer');
  const ids = new Set(S.job.objects.map((o) => o.id));
  for (const g of $$('g.obj', L)) if (!ids.has(g.dataset.id)) g.remove();
  for (const o of S.job.objects) {
    const data = await ensureGeo(o);
    let g = $(`g.obj[data-id="${CSS.escape(o.id)}"]`, L);
    if (!g || g.dataset.sig !== geo[o.id].sig) {
      if (g) g.remove();
      g = svgEl('g', { class: 'obj', 'data-id': o.id }, L);
      g.dataset.sig = geo[o.id].sig;
      svgEl('rect', { class: 'hit', x: 0, y: 0, width: data.size[0], height: data.size[1] }, g);
      for (const sh of data.shapes) {
        svgEl('path', { class: 'shape', d: sh.d, 'data-i': sh.i, 'fill-rule': sh.rule === 'evenodd' ? 'evenodd' : 'nonzero' }, g);
      }
    }
    placeObject(o);
    styleObject(o, g, data);
    drawMasks(o, g);
    g.style.display = hiddenObjs.has(o.id) ? 'none' : '';
    L.appendChild(g);             // the job's order: later on top, as it plots (emit.hidden)
  }
  markSmall();
  drawHandles();
  drawRulers();
}

// Shapes too small or dense for their tool's line (the slice says which): outlined in
// the Tools view, so it shows what 'too small' leaves out
function markSmall() {
  const small = (preview && preview.small) || {};
  for (const g of $$('#design-layer g.obj')) {
    const set = new Set(small[g.dataset.id] || []);
    for (const p of $$('path.shape', g)) p.classList.toggle('small', set.has(+p.dataset.i));
  }
}

// Its masked regions: nothing of the drawing is drawn in them (object mm, like its shapes)
function drawMasks(o, g) {
  for (const m of $$('.objmask', g)) m.remove();
  (o.masks || []).forEach((m, i) => {
    const d = 'M' + m.map(([x, y]) => `${x * o.scale},${y * o.scale}`).join(' L') + 'Z';
    const p = svgEl('path', { class: 'objmask' + (maskSel && maskSel.id === o.id && maskSel.i === i ? ' on' : ''), d, 'data-m': i }, g);
    svgEl('title', {}, p).textContent = 'Masked: not drawn here (the mask tool, M: click it, then Del)';
  });
}
async function removeMask(id, i) {
  const o = obj(id);
  if (!o) return;
  maskSel = null;
  await patchObj(id, { masks: o.masks.filter((_, k) => k !== i) });
}

function styleObject(o, g, data) {
  const paths = $$('path.shape', g);
  g.classList.toggle('selected', o.id === sel);
  g.classList.toggle('dim', view === 'paths');
  data.shapes.forEach((sh, n) => {
    const p = paths[n];
    let stroke = 'none', fill = 'none', sw = Math.max(sh.w, 0.1), op = 1, sop = 1, fop = 1;
    if (view === 'paths') {
      // Only a faint outline, if at all (the drawing toggle): the paths are what to look at
      stroke = 'var(--muted)'; sw = 0.12;
    } else if (view === 'original') {
      if (sh.line) { stroke = sh.fill; sw = 0.3; }
      else { stroke = sh.stroke || 'none'; fill = sh.fill || 'none'; }
      if (!sh.so) sop = 0.5;
      if (!sh.fo) fop = 0.5;
    } else {
      if (sh.line) {
        [stroke, op] = paintOf(effGroup(o, sh, 'fill'));
        sw = 0.3;
      } else {
        if (sh.stroke) [stroke, sop] = paintOf(effGroup(o, sh, 'stroke'));
        if (sh.fill) [fill, fop] = paintOf(effGroup(o, sh, 'fill'));
        if (fill === 'var(--paper)') { stroke = stroke === 'none' ? 'var(--muted)' : stroke; }
      }
    }
    p.setAttribute('stroke', stroke);
    p.setAttribute('stroke-width', sw);
    p.setAttribute('fill', fill);
    p.setAttribute('opacity', op);
    p.setAttribute('stroke-opacity', sop);
    p.setAttribute('fill-opacity', fop);
    p.setAttribute('stroke-linejoin', 'round');
    p.setAttribute('stroke-linecap', 'round');
  });
}

let runEls = [];
function renderPreview() {
  const L = $('#paths-layer');
  L.classList.remove('stale');
  L.innerHTML = '';
  runEls = [];
  const sc = $('#scrubber');
  if (!preview) { sc.max = 0; return; }
  const travel = $('#show-travel').checked;
  const show = view === 'paths';
  L.style.display = show ? '' : 'none';
  const parts = [];
  preview.runs.forEach(([k, t, line, flat], i) => {
    let pts = '';
    for (let j = 0; j < flat.length; j += 2) pts += flat[j] + ',' + flat[j + 1] + ' ';
    if (k === 0) {
      parts.push(`<polyline class="travel" data-r="${i}" points="${pts}"${travel ? '' : ' style="display:none"'}/>`);
    } else {
      const tool = S.tools[preview.tools[t]] || { color: '#222', width: 0.4 };
      parts.push(`<polyline data-r="${i}" points="${pts}" fill="none" stroke="${tool.color}" stroke-width="${tool.width}" stroke-linecap="round" stroke-linejoin="round"/>`);
    }
  });
  L.innerHTML = parts.join('') + '<circle class="head" r="0.9" cx="-100" cy="-100"/>';
  runEls = $$('polyline', L);
  sc.max = preview.lines;
  sc.value = preview.lines;
  scrubTo(preview.lines);
}

function scrubTo(line) {
  if (!preview) return;
  const travel = $('#show-travel').checked;
  let last = -1;
  preview.runs.forEach(([k, , l], i) => {
    const on = l <= line && (k !== 0 || travel);
    runEls[i].style.display = on ? '' : 'none';
    if (l <= line) last = i;
  });
  const head = $('#paths-layer .head');
  if (last >= 0 && line < preview.lines) {
    const f = preview.runs[last][3];
    head.setAttribute('cx', f[f.length - 2]); head.setAttribute('cy', f[f.length - 1]);
  } else if (head) { head.setAttribute('cx', -100); }
  $('#scrub-line').textContent = gcodeLines ? `${line}: ${gcodeLines[line - 1] || ''}` : `line ${line} / ${preview.lines}`;
  if (!$('#gcode-view').hidden) showGcode(line);
}

async function loadGcode() {
  if (!gcodeLines) gcodeLines = (await api('GET', '/api/gcode?inline=1')).split('\n');
}
function showGcode(line) {
  if (!gcodeLines) return;
  const v = $('#gcode-view');
  const a = Math.max(1, line - 12), b = Math.min(gcodeLines.length, line + 12);
  let h = '';
  for (let n = a; n <= b; n++) h += `<div class="${n === line ? 'cur' : ''}"><span class="n">${n}</span>${esc(gcodeLines[n - 1])}</div>`;
  v.innerHTML = h;
  const cur = $('.cur', v);
  if (cur) v.scrollTop = cur.offsetTop - v.clientHeight / 2;
}
$('#scrubber').addEventListener('input', async (e) => {
  stopPlay();
  await loadGcode();
  scrubTo(+e.target.value);
});
$('#gcode-toggle').addEventListener('click', async () => {
  const v = $('#gcode-view');
  v.hidden = !v.hidden;
  if (!v.hidden) { await loadGcode(); showGcode(+$('#scrubber').value); }
});
let playing = null;
function stopPlay() { if (playing) cancelAnimationFrame(playing); playing = null; $('#play').textContent = '▶'; }
$('#play').addEventListener('click', async () => {
  if (playing) return stopPlay();
  if (!preview) return;
  await loadGcode();
  if (view !== 'paths') setView('paths');
  const sc = $('#scrubber');
  let line = +sc.value >= preview.lines ? 0 : +sc.value;
  const step = Math.max(1, preview.lines / 600);
  $('#play').textContent = '❚❚';
  const tick = () => {
    line = Math.min(preview.lines, line + step);
    sc.value = line; scrubTo(Math.round(line));
    playing = line < preview.lines ? requestAnimationFrame(tick) : (stopPlay(), null);
  };
  playing = requestAnimationFrame(tick);
});

// --- panels -------------------------------------------------------------------
function toolOptions(g) {
  const cur = g && g.tool ? g.tool : g && g.mask ? 'mask' : 'skip';
  const opts = Object.values(S.tools).filter((t) => t.draws !== false).map((t) => `<option value="${esc(t.id)}"${cur === t.id ? ' selected' : ''}>${esc(t.id)} ${esc(t.name)}</option>`);
  opts.push(`<option value="mask"${cur === 'mask' ? ' selected' : ''}>mask</option>`);
  opts.push(`<option value="skip"${cur === 'skip' ? ' selected' : ''}>skip</option>`);
  return opts.join('');
}
const STROKES = { auto: 'auto width', centerline: 'centre line', width: 'full width' };
// How a tool draws (its fill, stroke, ..): the job's settings for all, its own tuning; no tool: the job's
const drawOf = (tid) => (tid && S.tools[tid]) || { ...S.draw, ...S.job.draw };
const opt = (v, cur, label) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label ?? v)}</option>`;

// The list has the top drawing first: one over another hides what is under it (where
// it paints opaque, its 'what is on top hides' on), on the canvas and on the paper
const ORDER = [['front', '⤒', 'Bring to front (Shift+])'], ['forward', '↑', 'Bring forward (])'],
  ['backward', '↓', 'Send backward ([)'], ['back', '⤓', 'Send to back (Shift+[)']];
function renderObjectList() {
  const ids = new Set(S.job.objects.map((o) => o.id));
  for (const id of hiddenObjs) if (!ids.has(id)) hiddenObjs.delete(id);
  const hidden = S.job.objects.filter((o) => hiddenObjs.has(o.id)).length;
  const n = S.job.objects.length;
  fill($('#objects'), [...S.job.objects].reverse().map((o, k) => `
    <li data-id="${esc(o.id)}" class="${o.id === sel ? 'on' : ''}${hiddenObjs.has(o.id) ? ' hidden' : ''}">
      <button class="icon eye" data-act="eye" title="${hiddenObjs.has(o.id) ? 'Hidden: show it' : 'Hide it (only from view: it still plots)'}">${hiddenObjs.has(o.id) ? '◌' : '◉'}</button>
      <span class="name">${esc(o.id)}</span>
      <button class="icon" data-act="dup" title="Duplicate (Ctrl+D)">⧉</button>
      <button class="icon" data-act="del" title="Remove (Del)">✕</button>
      ${o.id === sel && n > 1 ? `<div class="order" role="group" aria-label="Order">${ORDER.map(([to, icon, title]) =>
        `<button class="icon" data-order="${to}" title="${title}"${(to === 'front' || to === 'forward' ? k === 0 : k === n - 1) ? ' disabled' : ''}>${icon}</button>`).join('')}
        <span class="note">${k === 0 ? 'on top' : k === n - 1 ? 'at the bottom' : `${k + 1} of ${n}`}</span></div>` : ''}
    </li>`).join('') + (hidden ? `<li class="note">${hidden} hidden from view: ${hidden > 1 ? 'they still plot' : 'it still plots'} (Skip its colours not to)</li>` : ''));
}
$('#clear-objects').addEventListener('click', async (e) => {
  const n = S.job.objects.length;
  if (!n) return toast('Nothing on the bed');
  if (twice('clear-objects', e.currentTarget, `Remove all ${n} drawing${n > 1 ? 's' : ''} from the bed`)) {
    setState(await api('DELETE', '/api/objects'));
    sel = null;
    toast('Bed cleared (Undo brings it back)');
  }
});
async function reorder(id, to) {
  setState(await api('POST', `/api/objects/${id}/order`, { to }));
}
$('#objects').addEventListener('click', async (e) => {
  const li = e.target.closest('li'); if (!li) return;
  const id = li.dataset.id, act = e.target.dataset.act;
  if (!id) return;
  if (e.target.dataset.order) return reorder(id, e.target.dataset.order);
  if (act === 'eye') return setHidden(id, !hiddenObjs.has(id));
  if (act === 'del') {
    if (twice(`del-${id}`, e.target, `Remove ${id} from the bed`)) setState(await api('DELETE', `/api/objects/${id}`));
  } else if (act === 'dup') {
    const r = await api('POST', `/api/objects/${id}/duplicate`); sel = r.id; setState(r.state);
  } else { sel = id; store.set('sel', sel); render(); }
});

function renderObjectPanel() {
  const P = $('#object-panel');
  const o = sel && obj(sel);
  if (!o) { P.hidden = true; return; }
  P.hidden = false;
  const I = info(o.id);
  const groups = I.groups.map((g) => {
    const cur = o.groups[g.key] || g.default;
    const [part, colour] = g.key.split(' ');
    const over = !!o.groups[g.key];
    const open = openOpts.has(o.id + g.key);
    const meta = [`${g.shapes}×`, g.texts ? `${g.texts} text` : '', g.length ? `${num(g.length / 1000, 2)} m` : '',
      g.widths.length ? 'w ' + g.widths.slice(0, 3).map((w) => num(w, 2)).join('/') : ''].filter(Boolean).join(' · ');
    // Left empty: as its tool draws (the Drawing panel for every tool, a tool's own tuning)
    const t = drawOf(cur.tool);
    const opts = part === 'fill'
      ? `<select data-f="fill">${opt('', cur.fill ?? '', `${t.fill} (tool)`)}${['hatch', 'crosshatch', 'concentric', 'none'].map((v) => opt(v, cur.fill ?? '')).join('')}</select>
         <label>∠<input type="number" data-f="angle" value="${num(cur.angle)}" step="15" placeholder="${num(t.angle)}"></label>
         <select data-f="border">${opt('', cur.border == null ? '' : cur.border ? '1' : '0', `${t.border ? 'border' : 'no border'} (tool)`)}${opt('1', cur.border == null ? '' : cur.border ? '1' : '0', 'border')}${opt('0', cur.border == null ? '' : cur.border ? '1' : '0', 'no border')}</select>
         <label>gap<input type="number" data-f="spacing" value="${num(cur.spacing)}" step="0.05" min="0.05" placeholder="tool"></label>`
      : `<select data-f="stroke">${opt('', cur.stroke ?? '', `${STROKES[t.stroke]} (tool)`)}${Object.entries(STROKES).map(([v, l]) => opt(v, cur.stroke ?? '', l)).join('')}</select>`;
    return `<tr data-key="${esc(g.key)}">
        <td><span class="swatch ${part}" style="${part === 'stroke' ? 'border-color' : 'background'}:${esc(colour)}"></span></td>
        <td><div class="key">${esc(part)} ${esc(colour)}${over ? ' •' : ''}</div><div class="meta">${esc(meta)}</div></td>
        <td><select data-f="to">${toolOptions(cur)}</select></td>
        <td><button class="icon more" data-act="opts" title="Fill and stroke options">${open ? '▾' : '▸'}</button></td>
      </tr>${open ? `<tr data-key="${esc(g.key)}" class="opts-row"><td></td><td colspan="3"><div class="opts">${opts}</div></td></tr>` : ''}`;
  }).join('');
  const lineFonts = S.line_fonts;
  const srcFonts = S.fonts.filter((f) => f.kind === 'outline');
  const texts = I.texts.map((t) => {
    const s = t.spec;
    return `<div class="text-run" data-i="${t.index}">
      <div class="row"><span class="swatch" style="background:${esc(t.colour || '#000')}"></span>
        <b>“${esc(t.text.slice(0, 28))}”</b></div>
      <div class="meta">${esc(t.family || 'no font-family')} · ${num(t.size, 1)} mm · ${t.found ? 'source: ' + esc(t.found) : 'no source font uploaded'}</div>
      <div class="opts">
        <select data-f="mode">${[['auto', 'auto'], ['source', 'source font'], ['line', 'line font'], ['skip', 'skip']].map(([v, l]) => opt(v, s.mode, l)).join('')}</select>
        <select data-f="line_font" title="Line font">${lineFonts.map((f) => opt(f, s.line_font)).join('')}</select>
        <select data-f="fit" title="Line font size">${[['cap', 'cap height'], ['width', 'cap + width']].map(([v, l]) => opt(v, s.fit, l)).join('')}</select>
        <select data-f="font" title="Source font">${opt('', s.font || '', 'by family')}${srcFonts.map((f) => opt(f.file, s.font || '', `${f.family} ${f.style}`)).join('')}</select>
      </div></div>`;
  }).join('');
  const painted = Object.keys(o.shapes).length;
  fill(P, `
    <h3 class="objname">${esc(o.id)}</h3>
    <div class="form">
      <label for="f-x">X</label><div class="row"><input id="f-x" type="number" step="0.5" value="${num(o.placement.x)}"> <label for="f-y">Y</label><input id="f-y" type="number" step="0.5" value="${num(o.placement.y)}"></div>
      <label for="f-r">Rotate</label><div class="row"><input id="f-r" type="number" step="15" value="${num(o.placement.rotate)}"> <button data-act="rot90" title="R">⟲ 90°</button></div>
      <label for="f-s">Scale %</label><div class="row"><input id="f-s" type="number" step="1" min="1" value="${num(o.scale * 100, 1)}"> <button data-act="fit" title="Fit to the draw area">Fit</button> <button data-act="center">Centre</button></div>
      <label>Size</label><div>${num(I.size[0], 1)} × ${num(I.size[1], 1)} mm</div>
      <label></label><label class="check"><input type="checkbox" id="f-occ"${o.occlude ? ' checked' : ''}> what is on top hides what is under</label>
    </div>
    <h3>Colours (${I.groups.length})</h3>
    <table class="groups"><tbody>${groups}</tbody></table>
    ${I.texts.length ? `<h3>Texts (${I.texts.length})</h3>${texts}` : ''}
    <h3>Masked regions${o.masks.length ? ` (${o.masks.length})` : ''}</h3>
    ${o.masks.length ? `<ul class="list masks">${o.masks.map((m, i) => `<li data-m="${i}" class="${maskSel && maskSel.id === o.id && maskSel.i === i ? 'on' : ''}">
        <span class="name">${num(Math.max(...m.map((p) => p[0])) * o.scale - Math.min(...m.map((p) => p[0])) * o.scale, 1)} × ${num(Math.max(...m.map((p) => p[1])) * o.scale - Math.min(...m.map((p) => p[1])) * o.scale, 1)} mm</span>
        <button class="icon" data-unmask="${i}" title="Draw there again">✕</button></li>`).join('')}</ul>
        <div class="row"><button data-act="unmask-all">Clear all</button></div>`
      : `<p class="note">Nothing of it is drawn in a masked region, eg. over what is on the paper already. <button data-act="mask-tool" title="M">Mask tool</button></p>`}
    ${painted ? `<h3>Painted shapes</h3><div class="row">${painted} shape${painted > 1 ? 's' : ''} painted apart from their colour <button data-act="unpaint">Clear</button></div>` : ''}
    ${Object.keys(I.skipped || {}).length ? `<p class="note">Not drawn: ${esc(Object.entries(I.skipped).map(([k, v]) => `${v} ${k}`).join(', '))}</p>` : ''}`);
}

async function patchObj(id, body) { setState(await api('PATCH', `/api/objects/${id}`, body)); }

$('#object-panel').addEventListener('change', async (e) => {
  const o = obj(sel); if (!o) return;
  const t = e.target;
  if (t.id === 'f-x' || t.id === 'f-y' || t.id === 'f-r') {
    return patchObj(o.id, { placement: { x: +$('#f-x').value, y: +$('#f-y').value, rotate: +$('#f-r').value } });
  }
  if (t.id === 'f-s') return scaleTo(o, +t.value / 100);
  if (t.id === 'f-occ') return patchObj(o.id, { occlude: t.checked });
  const row = t.closest('tr[data-key]');
  if (row) {
    const key = row.dataset.key;
    const g = { ...(o.groups[key] || info(o.id).groups.find((x) => x.key === key).default) };
    const f = t.dataset.f;
    if (f === 'to') { g.tool = ['mask', 'skip'].includes(t.value) ? null : t.value; g.mask = t.value === 'mask'; }
    else if (f === 'border') g.border = t.value === '' ? null : t.value === '1';
    else if (f === 'angle' || f === 'spacing') g[f] = t.value === '' ? null : +t.value;
    else g[f] = t.value === '' ? null : t.value;
    return patchObj(o.id, { groups: { ...o.groups, [key]: g } });
  }
  const run = t.closest('.text-run');
  if (run) {
    const i = run.dataset.i;
    const spec = { ...(o.texts[i] || o.text), [t.dataset.f]: t.value === '' ? null : t.value };
    return patchObj(o.id, { texts: { ...o.texts, [i]: spec } });
  }
});
// Dragging X, Y, rotate or scale moves the drawing along; the server hears of it at the end
$('#object-panel').addEventListener('input', (e) => {
  const o = obj(sel);
  if (!o || !numDrag || !info(o.id)) return;
  const id = e.target.id;
  if (id === 'f-x' || id === 'f-y' || id === 'f-r') {
    o.placement = { x: +$('#f-x').value, y: +$('#f-y').value, rotate: +$('#f-r').value };
    placeObject(o);
  } else if (id === 'f-s') {
    const [w, h] = info(o.id).size, k = Math.max(0.01, +e.target.value / 100 / o.scale);
    placeObject({ ...o, placement: { ...o.placement, x: o.placement.x - (w * k - w) / 2, y: o.placement.y - (h * k - h) / 2 } }, k);
  } else return;
  $('#paths-layer').classList.add('stale');
  drawHandles();
  drawRulers();
});
$('#object-panel').addEventListener('click', async (e) => {
  const o = obj(sel); if (!o) return;
  const act = e.target.dataset.act;
  if (act === 'opts') {
    const k = o.id + e.target.closest('tr').dataset.key;
    openOpts.has(k) ? openOpts.delete(k) : openOpts.add(k);
    renderObjectPanel();
  } else if (act === 'rot90') {
    const [w, h] = info(o.id).size, c = { x: w / 2, y: h / 2 };
    const wc = toWorld(o.placement, c), a = (o.placement.rotate + 90) % 360, r = rot(c, a);
    patchObj(o.id, { placement: { x: +(wc.x - r.x).toFixed(3), y: +(wc.y - r.y).toFixed(3), rotate: a } });
  } else if (act === 'fit') {
    const [x0, y0, x1, y1] = S.machine.draw_area;
    const [w, h] = info(o.id).size.map((v) => v / o.scale);
    const s = 0.95 * Math.min((x1 - x0) / w, (y1 - y0) / h);
    await scaleTo(o, s, true);
  } else if (act === 'center') {
    centre(o);
  } else if (act === 'unpaint') {
    patchObj(o.id, { shapes: {} });
  } else if (act === 'unmask-all') {
    maskSel = null;
    patchObj(o.id, { masks: [] });
  } else if (act === 'mask-tool') {
    setMode('mask');
  } else if (e.target.dataset.unmask) {
    removeMask(o.id, +e.target.dataset.unmask);
  } else if (e.target.closest('.masks li')) {
    maskSel = { id: o.id, i: +e.target.closest('li').dataset.m };
    render();
  }
});

async function scaleTo(o, s, recentre = false) {
  // Keep the middle where it is (or centre it)
  const [w, h] = info(o.id).size;
  const k = s / o.scale;
  const p = { ...o.placement };
  if (!recentre) { p.x -= (w * k - w) / 2; p.y -= (h * k - h) / 2; }
  setState(await api('PATCH', `/api/objects/${o.id}`, { scale: +s.toFixed(4), placement: p }), { slice: !recentre });
  if (recentre) centre(obj(o.id));
}
function centre(o) {
  const [x0, y0, x1, y1] = S.machine.draw_area;
  const [w, h] = info(o.id).size;
  const r = o.placement.rotate * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  // the middle of the object, placed
  const mx = c * w / 2 - s * h / 2, my = s * w / 2 + c * h / 2;
  patchObj(o.id, { placement: { ...o.placement, x: +((x0 + x1) / 2 - mx).toFixed(2), y: +((y0 + y1) / 2 - my).toFixed(2) } });
}

function renderPalette() {
  const items = Object.values(S.tools).filter((t) => t.draws !== false).map((t) => `
    <button data-to="${esc(t.id)}" class="${paintTo === t.id ? 'on' : ''}">
      <span class="swatch" style="background:${esc(t.color)}"></span>${esc(t.id)} <span class="sub">${esc(t.name)} ${num(t.width)}</span>
    </button>`);
  for (const [v, label] of [['mask', 'Mask (hides)'], ['skip', 'Skip'], ['reset', 'Reset']]) {
    items.push(`<button data-to="${v}" class="${paintTo === v ? 'on' : ''}">${label}</button>`);
  }
  fill($('#palette'), items.join(''));
  svg.classList.toggle('painting', mode === 'paint' && !!paintTo);
  if (!drag) hint('');
}
$('#palette').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  paintTo = paintTo === b.dataset.to ? null : b.dataset.to;
  setMode(paintTo ? 'paint' : 'select');
});
for (const [id, set] of [['#paint-target', (v) => { paintTarget = v; }], ['#paint-scope', (v) => { paintScope = v; }]]) {
  $(id).addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    set(b.dataset.v);
    $$('button', $(id)).forEach((x) => x.classList.toggle('on', x === b));
    renderPalette();
  });
}
async function paintShape(id, index, scope) {
  setState(await api('POST', `/api/objects/${id}/paint`, { index, to: paintTo, target: paintTarget, scope }));
}

function renderOutput() {
  const st = preview && preview.stats;
  const mins = (s) => `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`;
  if (!st || !st.draw_mm) {
    $('#stats').innerHTML = '<span class="note">Nothing to plot yet.</span>';
  } else {
    const tools = Object.entries(st.tools).map(([id, t]) => {
      const tool = S.tools[id] || {};
      return `<div class="tool-line"><span class="swatch" style="background:${esc(tool.color || '#222')}"></span>${esc(id)} ${num(t.draw_mm / 1000, 2)} m · ${t.strokes} strokes</div>`;
    }).join('');
    $('#stats').innerHTML = `<div><b>~${mins(st.time_s)}</b> · ${st.tool_changes} tool change${st.tool_changes === 1 ? '' : 's'}</div>
      <div>draw ${num(st.draw_mm / 1000, 2)} m · travel ${num(st.travel_mm / 1000, 2)} m</div>${tools}`;
  }
  $('#problems').innerHTML = (preview ? preview.problems : []).map((p) => `<li>${esc(p)}</li>`).join('');
  for (const b of ['#upload', '#print']) {
    $(b).disabled = !st || !st.draw_mm || preview.unsafe;
    $(b).title = preview && preview.unsafe ? 'The pen would go under safe_z off the paper: see the problems' : '';
  }
}

const MACHINE_FIELDS = [['z_touch', 'z touch'], ['z_min', 'z min'], ['z_max', 'z max'], ['z_travel', 'z travel'], ['hop_distance', 'hop under'],
  ['clearance', 'clearance'], ['feed_travel', 'travel F'], ['order_time', 'order s']];
// Rarely needed fields fold away: <details> that remember whether they were open
function more(key, label, inner, n) {
  const open = store.get('more:' + key, false);
  return `<details class="more full" data-more="${key}"${open ? ' open' : ''}><summary>${esc(label)}${n ? ` <span class="note">${n}</span>` : ''}</summary>
    <div class="form">${inner}</div></details>`;
}
document.addEventListener('toggle', (e) => {
  const d = e.target;
  if (d.matches && d.matches('details[data-more]')) store.set('more:' + d.dataset.more, d.open);
}, true);

function renderMachine() {
  const m = S.machine, over = S.job.machine_overrides;
  const beds = Object.keys(S.beds);
  const follow = store.get('followBed', true);
  fill($('#machine'), `
    <label for="m-bed">Bed</label>
    <select id="m-bed">${opt('', m.bed_id || '', 'none')}${beds.map((b) => opt(b, m.bed_id)).join('')}</select>
    <label></label><label class="check"><input type="checkbox" id="m-follow"${follow ? ' checked' : ''}> follow Klipper</label>
    <label>Paper</label><div class="mono">${m.draw_area.map((v) => num(v, 1)).join(', ')}</div>
    <label>Mesh</label><div class="mono">${esc(m.mesh || '(last loaded)')}</div>
    ${MACHINE_FIELDS.filter(([k]) => k === 'z_touch' || k in over).map(field).join('')}
    ${more('machine', 'More settings', MACHINE_FIELDS.filter(([k]) => !(k === 'z_touch' || k in over)).map(field).join(''),
      MACHINE_FIELDS.filter(([k]) => !(k === 'z_touch' || k in over)).length)}`);
  function field([k, l]) {
    return `<label for="m-${k}">${l}</label><div class="row"><input id="m-${k}" data-k="${k}" type="number" step="0.1" value="${num(m[k])}"${k in over ? ' class="changed"' : ''}>${k in over ? ` <button class="icon" data-reset="${k}" title="Back to the profile">↺</button>` : ''}</div>`;
  }
}
$('#machine').addEventListener('change', async (e) => {
  const t = e.target;
  if (t.id === 'm-follow') { store.set('followBed', t.checked); return; }
  if (t.id === 'm-bed') return setState(await api('PATCH', '/api/job', { machine_overrides: { bed_id: t.value || null } }));
  if (t.dataset.k) setState(await api('PATCH', '/api/job', { machine_overrides: { [t.dataset.k]: +t.value } }));
});
$('#machine').addEventListener('click', async (e) => {
  const k = e.target.dataset.reset;
  if (k) setState(await api('PATCH', '/api/job', { machine_overrides: { [k]: null } }));
});

const TOOL_FIELDS = ['width', 'press', 'overlap', 'feed', 'z_down', 'hop', 'link', 'plunge_feed', 'wear', 'focus', 'power', 'reload_every', 'well_z', 'z_min', 'z_max', 'angle', 'bleed'];
// How it draws, whatever the pen (tools.DRAW): for every tool in the Drawing panel, one
// tool's own in its tuning. Number fields, then choices.
const PEN_OWN = new Set(['feed', 'plunge_feed', 'overlap', 'link']);     // empty: each pen's own
const DRAW_NUMS = [['feed', 'speed'], ['plunge_feed', 'plunge'], ['overlap', 'overlap'], ['link', 'link'], ['angle', 'fill ∠'], ['bleed', 'bleed']];
const DRAW_CHOICES = {
  fill: [['hatch', 'hatch'], ['crosshatch', 'crosshatch'], ['concentric', 'rings'], ['none', 'no fill']],
  border: [['1', 'border'], ['0', 'no border']],
  stroke: Object.entries(STROKES),
  small: [['skip', 'leave out'], ['warn', 'warn, draw'], ['draw', 'draw']],
  layers: [['1', 'light under dark'], ['0', 'cut out']],
};
const BOOL_CHOICES = new Set(['border', 'layers']);
const asChoice = (v) => (v === true ? '1' : v === false ? '0' : v ?? '');
const fromChoice = (k, v) => (v === '' ? null : BOOL_CHOICES.has(k) ? v === '1' : v);
const choiceLabel = (k, v) => (DRAW_CHOICES[k].find(([c]) => c === asChoice(v)) || [, String(v)])[1];
function choices(k, cur, dflt, attr) {
  return `<select ${attr}>${opt('', asChoice(cur), `${choiceLabel(k, dflt)} (default)`)}${DRAW_CHOICES[k].map(([v, l]) => opt(v, asChoice(cur), l)).join('')}</select>`;
}

function renderDraw() {
  const d = S.job.draw, base = S.draw;
  const nums = DRAW_NUMS.map(([k, l]) => `<label>${l}<input type="number" step="any" data-dk="${k}" value="${d[k] == null ? '' : num(d[k], 3)}"
      placeholder="${PEN_OWN.has(k) ? 'pen’s' : num(base[k], 3)}"${k in d ? ' class="changed"' : ''}></label>`).join('');
  const sels = Object.keys(DRAW_CHOICES).map((k) => `<label>${k === 'small' ? 'too small' : k}${choices(k, d[k], base[k], `data-dk="${k}"${k in d ? ' class="changed"' : ''}`)}</label>`).join('');
  const n = Object.keys(d).length;
  fill($('#drawset'), `<div class="grid">${nums}</div><div class="grid choices">${sels}</div>
    <p class="note">For every tool, whatever its pen; a tool’s tuning wins (Tools), a colour’s own fill and stroke over both.</p>
    ${n ? `<button class="icon" data-act="reset-draw" title="Back to each pen's and the defaults">↺ ${n} changed</button>` : ''}`);
}
$('#drawset').addEventListener('change', async (e) => {
  const k = e.target.dataset.dk;
  if (!k) return;
  const v = e.target.tagName === 'SELECT' ? fromChoice(k, e.target.value) : e.target.value === '' ? null : +e.target.value;
  setState(await api('PATCH', '/api/job', { draw: { [k]: v } }));
});
$('#drawset').addEventListener('click', async (e) => {
  if (e.target.dataset.act !== 'reset-draw') return;
  setState(await api('PATCH', '/api/job', { draw: Object.fromEntries(Object.keys(S.job.draw).map((k) => [k, null])) }));
});
// Each holder: what its tag says, and what the card would write to it (draft)
const drafts = {};
const openTune = new Set();     // tool cards with their tuning open
const penName = (key) => (S.pens[key] || {}).name || key || '';
function colourName(pen, hex) {
  const c = (S.pens[pen] || {}).colors || {};
  return Object.keys(c).find((k) => c[k].toLowerCase() === (hex || '').toLowerCase());
}
function suggestName(pen, hex) {
  const n = colourName(pen, hex);
  const short = (S.pens[pen] || {}).short || penName(pen);
  const colour = n ? ' ' + n.replace(/\b\w/g, (c) => c.toUpperCase()) : '';
  return (short + colour).length <= 20 ? (short + colour).trim() : (short.slice(0, 20 - colour.length) + colour).trim();
}
function draftOf(t, tag, tool) {
  const base = JSON.stringify(tag || null);
  if (!drafts[t] || drafts[t].base !== base) {
    drafts[t] = { base, pen: (tag && tag.pen) || '', color: (tag && tag.color) || tool.color || '#000000',
                  name: (tag && tag.name) || '', named: false };
  }
  return drafts[t];
}
function renderTools() {
  const over = S.job.tool_overrides;
  const job = printer && printer.job;
  const busy = !!(job && !job.done);
  const status = busy ? `${esc(job.what)}…` : job ? (job.error ? `⚠ ${esc(job.error)}` : `${esc(job.what)}: done`) : 'reads every tool’s tag';
  const scan = printer && printer.scan;
  const head = `<div class="row tools-head"><button data-act="scan"${busy ? ' disabled' : ''} title="TOOL_SCAN: each tool in turn to the tag reader">Scan holders</button>
    <span class="note">${status}</span></div>
    ${scan ? `<div class="scan-now"><span class="swatch" style="background:${esc(scan.color || '#888')}"></span>
      <b>${esc(scan.name)}</b> scanned: into its holder, ${Math.max(0, Math.round(scan.left))} s</div>`
    : '<p class="note">Or by hand: hold a pen to the reader until it beeps, then put it into a holder within 8 s.</p>'}`;
  const cards = S.holders.map(({ t, holder, tag }) => {
    const tool = S.tools[t] || {};
    if (tool.kind === 'camera') {
      // A camera: nothing to paint or press with; it is used from the Scan tab
      return `<div class="tool" data-t="${esc(t)}" data-holder="${holder}" title="A camera tool: it takes photos from the Scan tab">
        <div class="head"><span class="swatch cam">◉</span><b>${esc(t)}</b><span class="note">${holder}</span>
          <span class="tname" title="${esc(tool.name)}">${esc((tag && tag.name) || tool.name || '')}</span>
          ${tag ? '<span class="badge ok" title="Its tag names a camera type">camera</span>' : ''}</div>
        <div class="note mono" title="One shot, its focus height and the height it moves at (machine Z); in pens.toml">${esc(tool.pen || '')} · ${num(tool.fov[0], 1)} × ${num(tool.fov[1], 1)} mm · focus Z${num(tool.focus_z, 2)} · clear Z${num(tool.clear_z, 2)}</div>
      </div>`;
    }
    const o = over[t] || {};
    const d = draftOf(t, tag, tool);
    const badge = !tag ? '<span class="badge">not scanned</span>'
      : tag.stale ? '<span class="badge warn" title="A hand was on this holder since: scan it again, at the reader by hand or with Scan holders">stale</span>'
      : !tag.pen ? '<span class="badge warn" title="The tag has only a name: give it a pen">name only</span>'
      : tag.by === 'hand' ? '<span class="badge ok" title="Scanned by hand at the reader, then put into this holder">scanned</span>'
      : '<span class="badge ok">tag</span>';
    const pens = '<option value="">pen…</option>' + Object.entries(S.pens).map(([k, p]) =>
      `<option value="${esc(k)}"${k === d.pen ? ' selected' : ''}>${esc(p.name)} · ${num(p.width)} mm</option>`).join('')
      + '<option value="__new">new pen type…</option>';
    const sws = Object.entries((S.pens[d.pen] || {}).colors || {}).map(([n, hex]) =>
      `<button class="sw${hex.toLowerCase() === d.color.toLowerCase() ? ' on' : ''}" data-color="${esc(hex)}" title="${esc(n)}" style="background:${esc(hex)}"></button>`).join('');
    const changed = tag ? (d.pen !== (tag.pen || '') || d.color.toLowerCase() !== (tag.color || '').toLowerCase() || d.name !== (tag.name || ''))
      : !!d.pen;
    // with a press, z_down and hop don't count: pen-down is z_touch less it, the lift comes from it and the play
    const fields = TOOL_FIELDS.filter((k) => k in tool && !(tool.press != null && (k === 'z_down' || k === 'hop'))).map((k) =>
      `<label>${k.replace('_', ' ')}<input type="number" step="any" data-k="${k}" value="${tool[k] === null ? '' : num(tool[k], 3)}"${k === 'link' && tool[k] === null ? ` placeholder="${num(tool.width / 2, 3)}"` : ''}${k in o ? ' class="changed"' : ''}></label>`).join('');
    const sels = Object.keys(DRAW_CHOICES).map((k) => `<label>${k === 'small' ? 'too small' : k}${choices(k, k in o ? tool[k] : null,
      k in S.job.draw ? S.job.draw[k] : S.draw[k], `data-k="${k}" data-sel="1"${k in o ? ' class="changed"' : ''}`)}</label>`).join('');
    const tuned = Object.keys(o).length;
    const dry = ((printer && printer.drying) || {})[String(holder)];
    const dryBadge = dry ? `<span class="badge ${dry.stage ? 'bad' : 'warn'}" title="Out of its cap in the machine; ${Math.round(dry.limit / 60)} min allowed (TOOL_DRY RESET=1 T=${holder} after priming it)">uncapped ${Math.floor(dry.uncapped / 60)} min</span>` : '';
    return `<div class="tool" data-t="${esc(t)}" data-holder="${holder}">
      <div class="head"><span class="swatch" style="background:${esc(tool.color || '#000')}"></span><b>${esc(t)}</b>
        <span class="note">${holder}</span><span class="tname" title="${esc(tool.name)}">${esc((tag && tag.name) || tool.name || '')}</span>${badge}${dryBadge}</div>
      ${tag ? `<div class="note mono">${tag.pen ? esc(penName(tag.pen)) + ' · ' : ''}${num(tool.width)} mm · dx ${num(tag.dx)} dy ${num(tag.dy)} dz ${num(tag.dz)}</div>` : ''}
      <div class="assign">
        <select data-d="pen" title="The kind of pen (pens.toml)">${pens}</select>
        <div class="sws">${sws}<input type="color" data-d="color" value="${esc(d.color)}" title="Any colour"></div>
        <input data-d="name" maxlength="20" value="${esc(d.name)}" placeholder="${esc(suggestName(d.pen, d.color) || 'name')}" title="The tag's name, up to 20">
        <button data-act="write" class="${changed ? 'primary' : ''}"${busy || !changed ? ' disabled' : ''} title="Dock ${esc(t)}, write this onto its tag, put it back">Write to tag</button>
      </div>
      <details data-tune="${esc(t)}"${tuned || openTune.has(t) ? ' open' : ''}><summary>tune: ${esc(tool.kind || 'pen')} ${num(tool.width)} mm${tuned ? ' · changed here' : ''}</summary>
        <div class="grid">${fields}</div><div class="grid choices">${sels}</div>${tuned ? '<button class="icon" data-act="reset" title="Back to the pen library / tools.toml">↺ undo tuning</button>' : ''}</details>
    </div>`;
  }).join('');
  fill($('#tools'), head + cards);
}
function redraft(t, update) {
  const d = drafts[t];
  Object.assign(d, update);
  if (!d.named) d.name = suggestName(d.pen, d.color);
  renderTools();
}
$('#tools').addEventListener('change', async (e) => {
  const el = e.target, card = el.closest('.tool'); if (!card) return;
  const t = card.dataset.t;
  if (el.dataset.d === 'pen' && el.value === '__new') {
    el.value = drafts[t].pen;
    return editPen(null);
  }
  if (el.dataset.d === 'pen') {
    const colors = Object.values((S.pens[el.value] || {}).colors || {});
    const d = drafts[t];
    return redraft(t, { pen: el.value, color: colors.map((c) => c.toLowerCase()).includes(d.color.toLowerCase()) ? d.color : (colors[0] || d.color) });
  }
  if (el.dataset.d === 'color') return redraft(t, { color: el.value });
  if (el.dataset.d === 'name') { Object.assign(drafts[t], { name: el.value.trim(), named: !!el.value.trim() }); return renderTools(); }
  if (!el.dataset.k) return;
  const v = el.dataset.sel ? fromChoice(el.dataset.k, el.value) : el.value === '' ? null : +el.value;
  setState(await api('PATCH', '/api/job', { tool_overrides: { [t]: { [el.dataset.k]: v } } }));
});
$('#tools').addEventListener('click', async (e) => {
  const el = e.target;
  if (el.dataset.act === 'scan') {
    if (!twice('scan-tags', el, 'Take each tool to the tag reader in turn and read its tag')) return;
    printer = { ...(printer || {}), job: (await api('POST', '/api/scan', {})).job };
    renderTools(); watchJob();
    return;
  }
  const card = el.closest('.tool'); if (!card) return;
  const t = card.dataset.t;
  if (el.dataset.color) return redraft(t, { color: el.dataset.color });
  if (el.dataset.act === 'write') {
    const d = drafts[t], holder = card.dataset.holder;
    const what = [d.pen && penName(d.pen), colourName(d.pen, d.color) || d.color, d.name && `"${d.name}"`].filter(Boolean).join(', ');
    if (!twice(`write-${holder}`, el, `Dock ${t} (holder ${holder}), write ${what} onto its tag, and put it back`)) return;
    const r = await api('POST', `/api/holders/${holder}/tag`, { pen: d.pen, color: d.color, name: d.name || suggestName(d.pen, d.color) });
    printer = { ...(printer || {}), job: r.job };
    renderTools(); watchJob();
  } else if (el.dataset.act === 'reset') {
    const keys = Object.fromEntries(Object.keys(S.job.tool_overrides[t] || {}).map((k) => [k, null]));
    setState(await api('PATCH', '/api/job', { tool_overrides: { [t]: keys } }));
  }
});
$('#tools').addEventListener('toggle', (e) => {
  const t = e.target.dataset && e.target.dataset.tune;
  if (t) e.target.open ? openTune.add(t) : openTune.delete(t);
}, true);
let jobTimer = null;
function watchJob() {
  clearTimeout(jobTimer);
  jobTimer = setTimeout(async () => {
    await pollPrinter();
    const job = printer && printer.job;
    if (job && !job.done) watchJob();
  }, 2000);
}

function renderFonts() {
  fill($('#fonts'), S.fonts.map((f) => `
    <li><span class="name" title="${esc(f.file)}">${esc(f.family)} <span class="note">${esc(f.style)} · ${f.kind === 'line' ? 'line' : 'source'}</span></span>
    <button class="icon" data-del="${esc(f.file)}" title="Remove">✕</button></li>`).join('') || '<li class="note">No fonts uploaded: texts use line fonts.</li>');
}
$('#fonts').addEventListener('click', async (e) => {
  const f = e.target.dataset.del;
  if (f && twice(`font-${f}`, e.target, `Remove the font ${f}`)) setState(await api('DELETE', `/api/fonts/${encodeURIComponent(f)}`));
});
async function uploadFonts(files) {
  for (const f of files) {
    const fd = new FormData(); fd.append('file', f);
    const r = await api('POST', '/api/fonts', fd);
    toast(`${r.font.family} ${r.font.style}: ${r.font.kind === 'line' ? 'line font' : 'source font'}`);
    setState(r.state);
  }
}
$('#font-input').addEventListener('change', (e) => { uploadFonts([...e.target.files]); e.target.value = ''; });

// --- pen library (pens.toml) ---------------------------------------------------
// The kinds of pen a tag can name. The key goes on the tags: set once, never renamed.
let penEdit = null;             // {key, isNew, spec} being edited
const PEN_FIRST = ['width', 'press', 'press_max', 'feed', 'overlap'];
function editPen(key) {
  const spec = key ? JSON.parse(JSON.stringify(S.pens[key])) : { name: '', short: '', width: 0.3, colors: { black: '#1b1b1b' } };
  penEdit = { key: key || '', isNew: !key, spec, colors: Object.entries(spec.colors || {}) };
  renderPens();
  $('#pens').scrollIntoView({ block: 'nearest' });
  const first = $(key ? '#pens [data-p=name]' : '#pens [data-p=key]');
  if (first) first.focus();
}
function penFields(kind) {
  const fields = Object.keys((S.kinds || {})[kind] || (S.kinds || {}).pen || {});
  return [...PEN_FIRST.filter((f) => fields.includes(f)), ...fields.filter((f) => !PEN_FIRST.includes(f))];
}
function renderPens() {
  const users = (key) => S.holders.filter((h) => h.tag && h.tag.pen === key).map((h) => h.holder);
  const list = Object.entries(S.pens).map(([k, p]) => {
    const sws = Object.values(p.colors || {}).slice(0, 8).map((c) => `<span class="dot" style="background:${esc(c)}"></span>`).join('');
    const on = users(k);
    return `<li data-pen="${esc(k)}" class="${penEdit && penEdit.key === k ? 'on' : ''}">
      <span class="name">${esc(p.name)} <span class="note">${num(p.width)} mm${p.kind && p.kind !== 'pen' ? ' · ' + esc(p.kind) : ''}${on.length ? ' · in ' + on.join(', ') : ''}</span></span>
      <span class="dots">${sws}</span><span class="note mono">${esc(k)}</span></li>`;
  }).join('');
  let editor = '';
  if (penEdit) {
    const sp = penEdit.spec, kind = sp.kind || 'pen', defaults = (S.kinds || {})[kind] || {};
    const fields = penFields(kind).map((f) => {
      const d = defaults[f];
      return `<label>${f.replace('_', ' ')}<input type="number" step="any" data-pf="${f}" value="${sp[f] ?? ''}" placeholder="${d === null || d === undefined ? 'machine' : num(d, 3)}"></label>`;
    }).join('');
    const colors = penEdit.colors.map(([n, c], i) => `<div class="row pen-colour" data-i="${i}">
        <input type="color" data-c="hex" value="${esc(c)}"><input data-c="name" value="${esc(n)}" placeholder="colour name">
        <button class="icon" data-act="uncolour" title="Remove">✕</button></div>`).join('');
    editor = `<div class="pen-edit">
      <div class="form">
        <label>Key</label><input data-p="key" maxlength="8" value="${esc(penEdit.key)}"${penEdit.isNew ? '' : ' disabled'} placeholder="eg. uni-01" title="Goes on the tags: up to 8 of a-z 0-9 - _ . , never renamed">
        <label>Name</label><input data-p="name" value="${esc(sp.name || '')}" placeholder="Uni Pin 0.1">
        <label>Short</label><input data-p="short" maxlength="20" value="${esc(sp.short || '')}" placeholder="for tag names, ≤ 20" title="How tags name it, with the colour: up to 20 characters">
        <label>Uncapped</label><input data-p="dry" type="number" min="1" value="${esc(sp.dry ?? '')}" placeholder="10 min (the dock's default)" title="Minutes it may stay out of its cap in the machine before the dock goes red and beeps; twice that while printing">
        <label>Kind</label><select data-p="kind">${Object.keys(S.kinds || { pen: 1 }).map((k) => opt(k, kind)).join('')}</select>
      </div>
      <div class="grid">${fields}</div>
      <h3>Colours</h3>${colors}
      <button class="icon" data-act="colour">+ colour</button>
      <div class="buttons"><button class="primary" data-act="save-pen">${penEdit.isNew ? 'Add pen' : 'Save'}</button>
        <button data-act="cancel-pen">Cancel</button>
        ${penEdit.isNew ? '' : '<button data-act="delete-pen" class="danger">Delete</button>'}</div>
    </div>`;
  }
  fill($('#pens'), `<ul class="list">${list}</ul>${editor}${penEdit && penEdit.isNew ? '' : '<button data-act="new-pen">+ New pen type</button>'}`);
}
// The draft follows what is typed, without a redraw: the caret stays
$('#pens').addEventListener('input', (e) => {
  if (!penEdit) return;
  const t = e.target;
  if (t.dataset.p === 'key') penEdit.key = t.value.trim().toLowerCase();
  else if (t.dataset.p === 'dry') penEdit.spec.dry = t.value === '' ? undefined : +t.value;
  else if (t.dataset.p && t.dataset.p !== 'kind') penEdit.spec[t.dataset.p] = t.value;
  else if (t.dataset.pf) penEdit.spec[t.dataset.pf] = t.value === '' ? undefined : +t.value;
  else if (t.dataset.c) {
    const i = +t.closest('.pen-colour').dataset.i;
    penEdit.colors[i][t.dataset.c === 'hex' ? 1 : 0] = t.value;
  }
});
$('#pens').addEventListener('change', (e) => {
  if (penEdit && e.target.dataset.p === 'kind') {
    penEdit.spec.kind = e.target.value;
    const keep = new Set(penFields(e.target.value));
    for (const f of Object.keys(penEdit.spec)) if (!['name', 'short', 'kind', 'colors'].includes(f) && !keep.has(f)) delete penEdit.spec[f];
    renderPens();
  }
});
$('#pens').addEventListener('click', async (e) => {
  const t = e.target;
  const li = t.closest('li[data-pen]');
  if (li) return editPen(li.dataset.pen);
  const act = t.dataset.act;
  if (act === 'new-pen') return editPen(null);
  if (!penEdit) return;
  if (act === 'colour') { penEdit.colors.push(['', '#000000']); renderPens(); }
  else if (act === 'uncolour') { penEdit.colors.splice(+t.closest('.pen-colour').dataset.i, 1); renderPens(); }
  else if (act === 'cancel-pen') { penEdit = null; renderPens(); }
  else if (act === 'save-pen') {
    const spec = {};
    for (const [k, v] of Object.entries(penEdit.spec)) {
      if (k === 'colors' || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v))) continue;
      spec[k] = typeof v === 'string' ? v.trim() : v;
    }
    spec.colors = Object.fromEntries(penEdit.colors.filter(([n]) => n.trim()).map(([n, c]) => [n.trim(), c]));
    const key = penEdit.key;
    const st = await api('PUT', `/api/pens/${encodeURIComponent(key)}`, spec);
    penEdit = null;
    setState(st);
    toast(`Pen ${key} saved`);
  } else if (act === 'delete-pen') {
    const key = penEdit.key;
    const on = S.holders.filter((h) => h.tag && h.tag.pen === key).map((h) => h.holder);
    if (!twice(`pen-${key}`, e.target, `Delete the pen ${key} from the library${on.length ? ` (holders ${on.join(', ')} have it on their tags: they fall back to tools.toml)` : ''}`)) return;
    const st = await api('DELETE', `/api/pens/${encodeURIComponent(key)}`);
    penEdit = null;
    setState(st);
    toast(`Pen ${key} deleted`);
  }
});

// --- number fields: drag sideways ------------------------------------------------
// Press and drag a number field left or right to change it, Shift finer, Ctrl coarser;
// a click without moving types into it. `input` events while dragging, one `change` at the end.
const DRAG_STEP = {
  'f-x': 0.5, 'f-y': 0.5, 'f-r': 1, 'f-s': 1, angle: 5, spacing: 0.01,
  z_min: 0.05, z_max: 0.1, z_travel: 0.1, hop_distance: 1, clearance: 0.1, feed_travel: 100, order_time: 0.05,
  dry: 5, width: 0.01, press: 0.02, press_max: 0.02, z_touch: 0.05, overlap: 0.05, feed: 100, z_down: 0.05, hop: 0.05, link: 0.01, plunge_feed: 50, wear: 0.005,
  focus: 0.1, power: 5, reload_every: 10, well_z: 0.05, dips: 1, bleed: 0.05,
};
const NON_NEGATIVE = new Set(['press', 'press_max', 'f-s', 'spacing', 'hop_distance', 'clearance', 'feed_travel', 'order_time', 'width', 'overlap',
  'feed', 'link', 'plunge_feed', 'wear', 'power', 'reload_every', 'dips', 'bleed']);
const PX_PER_STEP = 6;
let numDrag = null;
const fieldOf = (input) => input.dataset.k || input.dataset.dk || input.dataset.f || input.dataset.pf || input.id;
function dragStep(input) {
  const s = DRAG_STEP[fieldOf(input)];
  if (s) return s;
  if (input.step && input.step !== 'any' && +input.step > 0) return +input.step;
  const v = Math.abs(parseFloat(input.value) || parseFloat(input.placeholder) || 0);
  return v ? Math.max(0.01, 10 ** Math.floor(Math.log10(v)) / 10) : 0.01;
}
const decimals = (step) => Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
document.addEventListener('pointerdown', (e) => {
  const input = e.target.closest && e.target.closest('input[type=number]');
  if (!input || e.button !== 0 || input.disabled || document.activeElement === input) return;
  e.preventDefault();         // no focus, no text selection: it may be a drag
  const v0 = parseFloat(input.value);
  numDrag = { input, lastX: e.clientX, x0: e.clientX, start: input.value, value: Number.isNaN(v0) ? (parseFloat(input.placeholder) || 0) : v0, moved: false };
  try { input.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ }
});
document.addEventListener('pointermove', (e) => {
  const d = numDrag;
  if (!d) return;
  if (!d.moved && Math.abs(e.clientX - d.x0) < 3) return;
  d.moved = true;
  document.body.classList.add('num-dragging');
  const step = dragStep(d.input) * (e.shiftKey ? 0.1 : (e.ctrlKey || e.metaKey) ? 10 : 1);
  d.value += (e.clientX - d.lastX) / PX_PER_STEP * step;
  d.lastX = e.clientX;
  let v = Math.round(d.value / step) * step;
  const min = d.input.min !== '' ? +d.input.min : NON_NEGATIVE.has(fieldOf(d.input)) ? 0 : -Infinity;
  const max = d.input.max !== '' ? +d.input.max : Infinity;
  v = Math.min(max, Math.max(min, v));
  const text = String(+v.toFixed(decimals(step)));
  if (d.input.value !== text) {
    d.input.value = text;
    d.input.dispatchEvent(new Event('input', { bubbles: true }));
  }
});
function endNumDrag() {
  const d = numDrag;
  if (!d) return;
  numDrag = null;
  document.body.classList.remove('num-dragging');
  if (d.moved) {
    if (d.input.value !== d.start) d.input.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    d.input.focus();
    d.input.select();
  }
  setTimeout(flushLater, 0);
}
document.addEventListener('pointerup', endNumDrag);
document.addEventListener('pointercancel', endNumDrag);

// --- printer ----------------------------------------------------------------
let printer = null;
let lastJob = null;
async function pollPrinter() {
  const before = printer && printer.job;
  try { printer = await api('GET', '/api/printer'); } catch { printer = { ok: false, error: 'server', job: before }; }
  const job = printer.job;
  if (job && job.done && lastJob && !lastJob.done && job.started === lastJob.started) {
    toast(job.error ? `${job.what}: ${job.error}` : `${job.what}: done`, !!job.error);
  }
  lastJob = job;
  if (printer.tools_changed) { setState(await api('GET', '/api/state'), { quiet: true }); loadMacros(); }
  else if (S) quietly(renderTools);
  const pill = $('#printer-pill');
  if (!printer.ok) {
    pill.textContent = 'printer offline'; pill.className = 'pill bad'; pill.title = printer.error || '';
  } else {
    const st = printer.state || '?';
    const pct = printer.progress && st === 'printing' ? ` ${Math.round(printer.progress * 100)}%` : '';
    pill.textContent = st + pct;
    pill.className = 'pill ' + (st === 'printing' ? 'busy' : st === 'error' ? 'bad' : 'ok');
    pill.title = printer.url;
    const bed = printer.bed && printer.bed !== 'NONE' ? printer.bed : '';
    if (store.get('followBed', true) && S && printer.bed !== undefined && bed !== (S.machine.bed_id || '')
        && (bed === '' || bed in S.beds)) {
      setState(await api('PATCH', '/api/job', { machine_overrides: { bed_id: bed || null } }), { quiet: true });
      toast(`Bed from Klipper: ${bed || 'none'}`);
    }
  }
  quietly(renderPrinter);
  quietly(renderMacros);
  if (printer.ok && macros && !macros.checked) loadMacros();      // Klipper is back: which it has
}
function renderPrinter() {
  const p = printer;
  if (!p) return;
  fill($('#printer'), p.ok ? `
    <label>State</label><div>${esc(p.state)}${p.file ? ' · ' + esc(p.file) : ''}</div>
    <label>Bed</label><div>${esc(p.bed ?? '?')}</div>
    <label>Tools home</label><div>${p.occupied ? esc(p.occupied.join(', ')) || 'none' : '?'}</div>
    <label>Homed</label><div>${esc(p.homed || 'no')}</div>
    <label>At</label><div class="mono note">${esc(p.url)}</div>`
    : `<div class="full note" title="${esc(p.error || '')}">Can't reach Moonraker at <span class="mono">${esc(p.url || '?')}</span>${
      /refused/i.test(p.error || '') ? ': nothing answers there' : /timed? ?out/i.test(p.error || '') ? ': it doesn\'t answer in time' : ''}.</div>`);
}
// Klipper's useful macros as buttons (the machine profile's, those Klipper has, one per holder)
let macros = null;
async function loadMacros() {
  try { macros = await api('GET', '/api/printer/macros'); } catch { macros = null; }
  renderMacros();
}
function renderMacros() {
  const el = $('#macros');
  if (!macros || !macros.macros.length) { fill(el, ''); return; }
  const job = printer && printer.job;
  const busy = !!(job && !job.done) || !!(printer && ['printing', 'paused'].includes(printer.state));
  const groups = {};
  for (const m of macros.macros) (groups[m.group] = groups[m.group] || []).push(m);
  fill(el, Object.entries(groups).map(([g, ms]) => `<div class="mgroup"><span class="mlabel">${esc(g)}</span>
      <div class="mbuttons">${ms.map((m) => `<button data-gcode="${esc(m.gcode)}" title="${esc((m.title ? m.title + ' · ' : '') + m.gcode)}"${busy ? ' disabled' : ''}>${m.color
        ? `<span class="swatch dot" style="background:${esc(m.color)}"></span>` : ''}${esc(m.label)}</button>`).join('')}</div></div>`).join('')
    + (busy && job && !job.done ? `<p class="note">${esc(job.what)}…</p>` : '')
    + (macros.checked ? '' : '<p class="note">Klipper didn’t answer: not every one of these may be there.</p>'));
}
$('#macros').addEventListener('click', async (e) => {
  const b = e.target.closest('button[data-gcode]');
  if (!b) return;
  const m = macros.macros.find((x) => x.gcode === b.dataset.gcode);
  if (m.confirm && !twice(`macro-${m.gcode}`, b, `${m.label}: send ${m.gcode} to Klipper (the machine moves)`)) return;
  const r = await api('POST', '/api/printer/macro', { gcode: m.gcode });
  printer = { ...(printer || {}), job: r.job };
  toast(`${m.gcode} sent`);
  renderMacros(); renderTools(); watchJob();
});

async function send(start) {
  if (start && !twice('print', $('#print'), 'Send this plot to Klipper and start it')) return;
  const r = await api('POST', '/api/printer/upload', { start });
  toast(`${r.file} ${start ? 'sent, plotting' : 'uploaded'}`);
  pollPrinter();
}
$('#upload').addEventListener('click', () => send(false));
$('#print').addEventListener('click', () => send(true));

// --- files: drop on the bed -----------------------------------------------------
async function addSvgs(files, at) {
  for (const f of files) {
    const fd = new FormData(); fd.append('file', f);
    const r = await api('POST', '/api/objects', fd);
    sel = r.id;
    if (at) {
      const s = r.state.objects[r.id].size;
      const o = r.state.job.objects.find((x) => x.id === r.id);
      setState(await api('PATCH', `/api/objects/${r.id}`, { placement: { ...o.placement, x: +(at.x - s[0] / 2).toFixed(2), y: +(at.y - s[1] / 2).toFixed(2) } }));
    } else setState(r.state);
    toast(`${r.id} added` + (r.images ? ` · ${r.images} image${r.images > 1 ? 's' : ''} taken out: they can't be plotted` : ''));
  }
}
$('#svg-input').addEventListener('change', (e) => { addSvgs([...e.target.files]); e.target.value = ''; });
window.addEventListener('dragover', (e) => { e.preventDefault(); $('#drop').classList.add('over'); });
window.addEventListener('dragleave', () => $('#drop').classList.remove('over'));
window.addEventListener('drop', (e) => {
  e.preventDefault();
  $('#drop').classList.remove('over');
  const files = [...e.dataTransfer.files];
  const svgs = files.filter((f) => /\.svg$/i.test(f.name) && !/font/i.test(f.name));
  const fonts = files.filter((f) => /\.(ttf|otf)$/i.test(f.name));
  if (fonts.length) uploadFonts(fonts);
  if (svgs.length) addSvgs(svgs, e.target.closest && e.target.closest('#canvas') ? worldPt(e) : null);
});

// --- keys, view --------------------------------------------------------------------
function setView(v) {
  view = v; store.set('view', v);
  $$('#views button').forEach((b) => b.classList.toggle('on', b.dataset.view === v));
  $('#paths-layer').style.display = v === 'paths' ? '' : 'none';
  showDrawing();
  renderObjects();
}
function showDrawing() {
  $('#design-layer').style.display = view === 'paths' && !$('#show-drawing').checked ? 'none' : '';
  store.set('showDrawing', $('#show-drawing').checked);
}
$('#show-drawing').checked = store.get('showDrawing', false);
$('#show-drawing').addEventListener('change', showDrawing);
$('#views').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setView(b.dataset.view); });
$('#show-travel').addEventListener('change', () => { if (preview) scrubTo(+$('#scrubber').value); });
$('#show-art').addEventListener('change', () => { bedSig = null; renderBed(); });
function setPaper(colour) {
  svg.style.setProperty('--paper', colour);
  $('#paper-color').value = colour;
  store.set('paper', colour);
}
$('#paper-color').addEventListener('input', (e) => setPaper(e.target.value));
setPaper(store.get('paper', '#ffffff'));
$('#zoom-fit').addEventListener('click', fit);
$('#zoom-in').addEventListener('click', () => zoom(0.8));
$('#zoom-out').addEventListener('click', () => zoom(1.25));

// Keyboard shortcuts: the table is the help (?) too
const KEYS = [
  ['Tools', [['V', 'select, move, scale, turn'], ['H', 'pan (or hold Space, or the right button)'], ['P', 'paint with a tool'],
    ['Shift+0 … 9', 'paint with T0 … T9'], ['M', 'mask: drag over a drawing where it isn’t drawn'], ['Esc', 'stop: back to select, then deselect']]],
  ['View', [['1  2  3', 'Original · Tools · Paths'], ['F  0', 'fit the bed'], ['Z', 'zoom to the selected drawing'], ['+  −', 'zoom in, out'],
    ['T', 'travels in the Paths view'], ['G', 'the G-code beside the canvas'], ['\\', 'hide or show the panels'], ['?', 'these shortcuts']]],
  ['The selected drawing', [['← → ↑ ↓', 'nudge 1 mm (Shift 10, Alt 0.1)'], ['R  Shift+R', 'turn a quarter, either way'], ['C', 'centre it on the paper'],
    ['Tab  Shift+Tab', 'select the next, the previous drawing'], [']  [', 'bring forward, send backward'], ['Shift+]  Shift+[', 'to the front, to the back'],
    ['Ctrl+D', 'duplicate'], ['Del', 'remove it (a masked region, with the mask tool)']]],
  ['Plot', [['K', 'play the plot, pause'], [',  .', 'one G-code line back, on'], ['Shift+,  Shift+.', '100 lines back, on'], ['Home  End', 'the first line, the last'],
    ['Ctrl+S', 'download the G-code'], ['Ctrl+Z  Ctrl+Shift+Z', 'undo, redo']]],
  ['Canvas', [['wheel, pinch', 'zoom'], ['two fingers', 'pan (a trackpad, a touch screen)'], ['drag a corner', 'scale (Alt: about the middle)'],
    ['drag the knob', 'turn (Shift: 15° steps)'], ['drag a number', 'change it (Shift finer, Ctrl coarser)']]],
];
function toggleKeys(show) {
  const el = $('#keys-help');
  show = show ?? el.hidden;
  if (show) {
    el.innerHTML = `<div class="card"><h2>Keyboard shortcuts <button class="icon" data-act="keys-close" title="Close (Esc)">✕</button></h2>
      <div class="cols">${KEYS.map(([h, ks]) => `<section><h3>${h}</h3><dl>${ks.map(([k, d]) =>
        `<dt>${k.split('  ').map((x) => `<kbd>${esc(x)}</kbd>`).join(' ')}</dt><dd>${esc(d)}</dd>`).join('')}</dl></section>`).join('')}</div></div>`;
  }
  el.hidden = !show;
}
$('#keys-help').addEventListener('click', (e) => { if (e.target === e.currentTarget || e.target.dataset.act === 'keys-close') toggleKeys(false); });
document.addEventListener('click', (e) => {
  const k = e.target.closest && e.target.closest('[data-act="keys"]');
  if (k) { e.preventDefault(); toggleKeys(); }
});
function zoomToSel() {
  const o = sel && obj(sel);
  if (!o || !info(o.id)) return fit();
  const [w, h] = info(o.id).size;
  const c = [[0, 0], [w, 0], [w, h], [0, h]].map(([x, y]) => toWorld(o.placement, { x, y }));
  const xs = c.map((p) => p.x), ys = c.map((p) => p.y), m = Math.max(w, h) * 0.08 + 2;
  fitTo(Math.min(...xs) - m, Math.min(...ys) - m, Math.max(...xs) + m, Math.max(...ys) + m);
}
async function scrubBy(d, to) {
  if (!preview) return;
  stopPlay();
  await loadGcode();
  const sc = $('#scrubber');
  const line = Math.max(0, Math.min(preview.lines, to ?? +sc.value + d));
  if (view !== 'paths') setView('paths');
  sc.value = line;
  scrubTo(line);
}

window.addEventListener('keydown', async (e) => {
  if (e.target.closest && e.target.closest('input, select, textarea')) return;
  if (!$('#keys-help').hidden && (e.key === 'Escape' || e.key === '?')) { e.preventDefault(); return toggleKeys(false); }
  if (document.body.classList.contains('tab-scan') && window.scanKey && window.scanKey(e)) return;
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  if (mod && key === 'z') { e.preventDefault(); return undo(e.shiftKey); }
  if (mod && key === 'y') { e.preventDefault(); return undo(true); }
  if (mod && key === 's') { e.preventDefault(); return $('#download').click(); }
  if (e.key === ' ') { spaceDown = true; svg.classList.add('pan-mode'); e.preventDefault(); return; }
  if (e.key === '?') return toggleKeys(true);
  if (e.key === 'Escape') {
    if (mode !== 'select') setMode('select');
    else if (sel) { sel = null; store.set('sel', sel); render(); }
    return;
  }
  if (mod) {
    const o = sel && obj(sel);
    if (key === 'd' && o) {
      e.preventDefault();
      const r = await api('POST', `/api/objects/${o.id}/duplicate`); sel = r.id; setState(r.state);
    }
    return;
  }
  if (document.body.classList.contains('tab-scan')) {          // the rest is the Plot tab's
    if (key === '+' || key === '=') zoom(0.8);
    else if (key === '-') zoom(1.25);
    return;
  }
  const digit = /^Digit(\d)$/.exec(e.code);
  if (digit && e.shiftKey) {
    const t = S.tools[`T${digit[1]}`];
    if (!t || t.draws === false) return flash(`No T${digit[1]} to paint with`);
    paintTo = t.id;
    return setMode('paint');
  }
  if (digit && !e.altKey && ['1', '2', '3'].includes(digit[1])) return setView(['original', 'tools', 'paths'][+digit[1] - 1]);
  if (digit && digit[1] === '0') return fit();
  if (key === 'v') return setMode('select');
  if (key === 'h') return setMode('pan');
  if (key === 'p') return setMode('paint');
  if (key === 'm') return setMode('mask');
  if (key === 'f') return fit();
  if (key === 'z') return zoomToSel();
  if (key === '+' || key === '=') return zoom(0.8);
  if (key === '-') return zoom(1.25);
  if (key === 't') { $('#show-travel').click(); return; }
  if (key === 'g') { $('#gcode-toggle').click(); return; }
  if (key === 'k') { $('#play').click(); return; }
  if (e.code === 'Comma') return scrubBy(e.shiftKey ? -100 : -1);
  if (e.code === 'Period') return scrubBy(e.shiftKey ? 100 : 1);
  if (e.key === 'Home') return scrubBy(0, 0);
  if (e.key === 'End') return scrubBy(0, preview ? preview.lines : 0);
  if (e.key === 'Tab' && S.job.objects.length) {
    e.preventDefault();
    const ids = [...S.job.objects].reverse().map((o) => o.id);        // as the list has them: top first
    const i = ids.indexOf(sel);
    sel = ids[((i < 0 ? (e.shiftKey ? 0 : -1) : i) + (e.shiftKey ? -1 : 1) + ids.length) % ids.length];
    store.set('sel', sel);
    return render();
  }
  const o = sel && obj(sel);
  if (!o) return;
  if (mode === 'mask' && maskSel && maskSel.id === o.id && (e.key === 'Delete' || e.key === 'Backspace')) {
    e.preventDefault();
    return removeMask(o.id, maskSel.i);
  }
  if (e.code === 'BracketRight') return reorder(o.id, e.shiftKey ? 'front' : 'forward');
  if (e.code === 'BracketLeft') return reorder(o.id, e.shiftKey ? 'back' : 'backward');
  if (key === 'c') return centre(o);
  const d = e.shiftKey ? 10 : e.altKey ? 0.1 : 1;
  const moves = { ArrowLeft: [-d, 0], ArrowRight: [d, 0], ArrowUp: [0, d], ArrowDown: [0, -d] };
  if (moves[e.key]) {
    e.preventDefault();
    const [dx, dy] = moves[e.key];
    o.placement = { ...o.placement, x: +(o.placement.x + dx).toFixed(2), y: +(o.placement.y + dy).toFixed(2) };
    placeObject(o);
    drawHandles();
    clearTimeout(o._nudge);
    o._nudge = setTimeout(() => patchObj(o.id, { placement: o.placement }), 300);
  } else if (key === 'r') {
    // a quarter turn about the middle
    const [w, h] = info(o.id).size, c = { x: w / 2, y: h / 2 };
    const wc = toWorld(o.placement, c), a = (o.placement.rotate + (e.shiftKey ? 270 : 90)) % 360, r = rot(c, a);
    patchObj(o.id, { placement: { x: +(wc.x - r.x).toFixed(3), y: +(wc.y - r.y).toFixed(3), rotate: a } });
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    setState(await api('DELETE', `/api/objects/${o.id}`));
    toast(`${o.id} removed · Ctrl+Z brings it back`);
  }
});
window.addEventListener('keyup', (e) => { if (e.key === ' ') { spaceDown = false; svg.classList.toggle('pan-mode', mode === 'pan'); } });
$('#rail').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.mode) setMode(b.dataset.mode);
  else if (b.dataset.act === 'undo') undo();
  else if (b.dataset.act === 'redo') undo(true);
  else if (b.dataset.act === 'fit') fit();
});

function render() {
  renderBed();
  renderObjects();
  renderObjectList();
  renderObjectPanel();
  renderPalette();
  renderMachine();
  renderDraw();
  renderTools();
  renderPens();
  renderFonts();
  renderOutput();
}

(async function start() {
  S = await api('GET', '/api/state');
  fit();
  setView(view);
  setState(S);
  pollPrinter();
  loadMacros();
  // Quicker while a tool scanned by hand waits for its holder
  (function poll() {
    setTimeout(async () => {
      if (!document.hidden) { try { await pollPrinter(); } catch { /* offline: shown */ } }
      poll();
    }, printer && printer.scan ? 1000 : 3000);
  })();
})();
