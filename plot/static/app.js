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

let toastTimer = null;
function toast(msg, bad = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (bad ? ' bad' : '');
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 3000);
}

function setState(s, { slice = true } = {}) {
  S = s;
  if (sel && !S.job.objects.some((o) => o.id === sel)) sel = null;
  if (!sel && S.job.objects.length) sel = S.job.objects[0].id;
  store.set('sel', sel);
  render();
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
function fit() {
  const [x0, y0, x1, y1] = extent();
  const pad = 6;
  vb = { x: x0 - pad, y: -y1 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad };
  applyVb();
}
function applyVb() {
  svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  requestAnimationFrame(() => { drawRulers(); drawHandles(); });
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
svg.addEventListener('wheel', (e) => {
  e.preventDefault();
  zoom(Math.exp(e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), userPt(e));
}, { passive: false });

let spaceDown = false;
let mode = 'select';    // select | pan | paint
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
  else if (!paintTo) paintTo = Object.keys(S.tools)[0];
  $$('#rail [data-mode]').forEach((b) => b.classList.toggle('on', b.dataset.mode === m));
  svg.classList.toggle('pan-mode', m === 'pan');
  renderPalette();
  drawHandles();
}

svg.addEventListener('pointerdown', (e) => {
  const handle = e.target.closest('[data-handle]');
  const shape = e.target.closest('path.shape');
  const g = e.target.closest('g.obj');
  const capture = () => { try { svg.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ } };
  if (e.button === 1 || spaceDown || mode === 'pan' || (e.button === 0 && !g && !handle)) {
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
  if (mode === 'paint' && paintTo) {
    if (shape) paintShape(id, +shape.dataset.i, e.shiftKey ? 'colour' : paintScope);
    return;
  }
  if (sel !== id) { sel = id; store.set('sel', sel); render(); }
  const o = obj(id);
  drag = { kind: 'move', id, start: worldPt(e), p: { ...o.placement }, moved: false };
  capture();
});

svg.addEventListener('pointermove', (e) => {
  const w = worldPt(e);
  cursor = w;
  drawRulers();
  if (!drag) return;
  if (drag.kind === 'pan') {
    const r = svg.getBoundingClientRect();
    const s = Math.max(drag.vb.w / r.width, drag.vb.h / r.height);
    if (Math.abs(e.clientX - drag.cx) + Math.abs(e.clientY - drag.cy) > 3) drag.click = false;
    vb = { ...drag.vb, x: drag.vb.x - (e.clientX - drag.cx) * s, y: drag.vb.y - (e.clientY - drag.cy) * s };
    applyVb();
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
  if (!d.moved) return;
  const o = obj(d.id);
  const body = { placement: o.placement };
  if (d.kind === 'scale') body.scale = +(d.scale * d.k).toFixed(5);
  setState(await api('PATCH', `/api/objects/${d.id}`, body));
});

function hint(text) {
  $('#hint').textContent = text || (mode === 'paint' && paintTo
    ? `Painting ${paintTo} · ${paintTarget} · ${paintScope} (shift: whole colour) · Esc to stop` : '');
}

// The selected object's frame: corners scale (alt: about the middle), the knob turns (shift: 15°)
function drawHandles() {
  const L = $('#overlay-layer');
  L.innerHTML = '';
  const o = sel && obj(sel);
  if (!o || !info(o.id) || mode === 'paint') return;
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
  const box = $('#stage').getBoundingClientRect();
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
  }
  drawHandles();
  drawRulers();
}

function styleObject(o, g, data) {
  const paths = $$('path.shape', g);
  g.classList.toggle('selected', o.id === sel);
  g.classList.toggle('dim', view === 'paths');
  data.shapes.forEach((sh, n) => {
    const p = paths[n];
    let stroke = 'none', fill = 'none', sw = Math.max(sh.w, 0.1), op = 1, sop = 1, fop = 1;
    if (view === 'original' || view === 'paths') {
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
  const opts = Object.values(S.tools).map((t) => `<option value="${esc(t.id)}"${cur === t.id ? ' selected' : ''}>${esc(t.id)} ${esc(t.name)}</option>`);
  opts.push(`<option value="mask"${cur === 'mask' ? ' selected' : ''}>mask</option>`);
  opts.push(`<option value="skip"${cur === 'skip' ? ' selected' : ''}>skip</option>`);
  return opts.join('');
}
const opt = (v, cur, label) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label ?? v)}</option>`;

function renderObjectList() {
  $('#objects').innerHTML = S.job.objects.map((o) => `
    <li data-id="${esc(o.id)}" class="${o.id === sel ? 'on' : ''}">
      <span class="name">${esc(o.id)}</span>
      <button class="icon" data-act="dup" title="Duplicate">⧉</button>
      <button class="icon" data-act="del" title="Remove">✕</button>
    </li>`).join('');
}
$('#objects').addEventListener('click', async (e) => {
  const li = e.target.closest('li'); if (!li) return;
  const id = li.dataset.id, act = e.target.dataset.act;
  if (act === 'del') {
    if (confirm(`Remove ${id} from the bed?`)) setState(await api('DELETE', `/api/objects/${id}`));
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
    const opts = part === 'fill'
      ? `<select data-f="fill">${['hatch', 'crosshatch', 'concentric', 'none'].map((v) => opt(v, cur.fill)).join('')}</select>
         <label>∠<input type="number" data-f="angle" value="${num(cur.angle)}" step="15"></label>
         <label><input type="checkbox" data-f="border"${cur.border ? ' checked' : ''}> border</label>
         <label>gap<input type="number" data-f="spacing" value="${num(cur.spacing)}" step="0.05" min="0.05" placeholder="tool"></label>`
      : `<select data-f="stroke">${[['auto', 'auto width'], ['centerline', 'centre line'], ['width', 'full width']].map(([v, l]) => opt(v, cur.stroke, l)).join('')}</select>`;
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
  P.innerHTML = `
    <h2>${esc(o.id)}</h2>
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
    ${painted ? `<h3>Painted shapes</h3><div class="row">${painted} shape${painted > 1 ? 's' : ''} painted apart from their colour <button data-act="unpaint">Clear</button></div>` : ''}
    ${Object.keys(I.skipped || {}).length ? `<p class="note">Not drawn: ${esc(Object.entries(I.skipped).map(([k, v]) => `${v} ${k}`).join(', '))}</p>` : ''}`;
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
    else if (f === 'border') g.border = t.checked;
    else if (f === 'angle') g.angle = +t.value;
    else if (f === 'spacing') g.spacing = t.value === '' ? null : +t.value;
    else g[f] = t.value;
    return patchObj(o.id, { groups: { ...o.groups, [key]: g } });
  }
  const run = t.closest('.text-run');
  if (run) {
    const i = run.dataset.i;
    const spec = { ...(o.texts[i] || o.text), [t.dataset.f]: t.value === '' ? null : t.value };
    return patchObj(o.id, { texts: { ...o.texts, [i]: spec } });
  }
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
  const items = Object.values(S.tools).map((t) => `
    <button data-to="${esc(t.id)}" class="${paintTo === t.id ? 'on' : ''}">
      <span class="swatch" style="background:${esc(t.color)}"></span>${esc(t.id)} <span class="sub">${esc(t.name)} ${num(t.width)}</span>
    </button>`);
  for (const [v, label] of [['mask', 'Mask (hides)'], ['skip', 'Skip'], ['reset', 'Reset']]) {
    items.push(`<button data-to="${v}" class="${paintTo === v ? 'on' : ''}">${label}</button>`);
  }
  $('#palette').innerHTML = items.join('');
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
  for (const b of ['#upload', '#print']) $(b).disabled = !st || !st.draw_mm;
}

const MACHINE_FIELDS = [['z_min', 'z min'], ['z_max', 'z max'], ['z_travel', 'z travel'], ['hop_distance', 'hop under'],
  ['clearance', 'clearance'], ['feed_travel', 'travel F'], ['order_time', 'order s']];
function renderMachine() {
  const m = S.machine, over = S.job.machine_overrides;
  const beds = Object.keys(S.beds);
  const follow = store.get('followBed', true);
  $('#machine').innerHTML = `
    <label for="m-bed">Bed</label>
    <select id="m-bed">${opt('', m.bed_id || '', 'none')}${beds.map((b) => opt(b, m.bed_id)).join('')}</select>
    <label></label><label class="check"><input type="checkbox" id="m-follow"${follow ? ' checked' : ''}> follow Klipper</label>
    <label>Paper</label><div class="mono">${m.draw_area.map((v) => num(v, 1)).join(', ')}</div>
    <label>Mesh</label><div class="mono">${esc(m.mesh || '(last loaded)')}</div>
    ${MACHINE_FIELDS.map(([k, l]) => `<label for="m-${k}">${l}</label><div class="row"><input id="m-${k}" data-k="${k}" type="number" step="0.1" value="${num(m[k])}"${k in over ? ' class="changed"' : ''}>${k in over ? ` <button class="icon" data-reset="${k}" title="Back to the profile">↺</button>` : ''}</div>`).join('')}`;
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

const TOOL_FIELDS = ['width', 'overlap', 'feed', 'z_down', 'hop', 'link', 'plunge_feed', 'wear', 'focus', 'power', 'reload_every', 'well_z', 'z_min', 'z_max'];
// Each holder: what its tag says, and what the card would write to it (draft)
const drafts = {};
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
  const head = `<div class="row tools-head"><button data-act="scan"${busy ? ' disabled' : ''} title="TOOL_SCAN: each tool in turn to the tag reader">Scan holders</button>
    <span class="note">${status}</span></div>`;
  const cards = S.holders.map(({ t, holder, tag }) => {
    const tool = S.tools[t] || {};
    const o = over[t] || {};
    const d = draftOf(t, tag, tool);
    const badge = !tag ? '<span class="badge">not scanned</span>'
      : tag.stale ? '<span class="badge warn" title="A hand was on this holder since: scan it again">stale</span>'
      : tag.pen ? '<span class="badge ok">tag</span>' : '<span class="badge warn" title="The tag has only a name: give it a pen">name only</span>';
    const pens = '<option value="">pen…</option>' + Object.entries(S.pens).map(([k, p]) =>
      `<option value="${esc(k)}"${k === d.pen ? ' selected' : ''}>${esc(p.name)} · ${num(p.width)} mm</option>`).join('');
    const sws = Object.entries((S.pens[d.pen] || {}).colors || {}).map(([n, hex]) =>
      `<button class="sw${hex.toLowerCase() === d.color.toLowerCase() ? ' on' : ''}" data-color="${esc(hex)}" title="${esc(n)}" style="background:${esc(hex)}"></button>`).join('');
    const changed = tag ? (d.pen !== (tag.pen || '') || d.color.toLowerCase() !== (tag.color || '').toLowerCase() || d.name !== (tag.name || ''))
      : !!d.pen;
    const fields = TOOL_FIELDS.filter((k) => k in tool).map((k) =>
      `<label>${k.replace('_', ' ')}<input type="number" step="any" data-k="${k}" value="${tool[k] === null ? '' : num(tool[k], 3)}"${k === 'link' && tool[k] === null ? ` placeholder="${num(tool.width / 2, 3)}"` : ''}${k in o ? ' class="changed"' : ''}></label>`).join('');
    const tuned = Object.keys(o).length;
    return `<div class="tool" data-t="${esc(t)}" data-holder="${holder}">
      <div class="head"><span class="swatch" style="background:${esc(tool.color || '#000')}"></span><b>${esc(t)}</b>
        <span class="note">${holder}</span><span class="tname" title="${esc(tool.name)}">${esc((tag && tag.name) || tool.name || '')}</span>${badge}</div>
      ${tag ? `<div class="note mono">${tag.pen ? esc(penName(tag.pen)) + ' · ' : ''}${num(tool.width)} mm · dx ${num(tag.dx)} dy ${num(tag.dy)} dz ${num(tag.dz)}</div>` : ''}
      <div class="assign">
        <select data-d="pen" title="The kind of pen (pens.toml)">${pens}</select>
        <div class="sws">${sws}<input type="color" data-d="color" value="${esc(d.color)}" title="Any colour"></div>
        <input data-d="name" maxlength="20" value="${esc(d.name)}" placeholder="${esc(suggestName(d.pen, d.color) || 'name')}" title="The tag's name, up to 20">
        <button data-act="write" class="${changed ? 'primary' : ''}"${busy || !changed ? ' disabled' : ''} title="Dock ${esc(t)}, write this onto its tag, put it back">Write to tag</button>
      </div>
      <details${tuned ? ' open' : ''}><summary>tune: ${esc(tool.kind || 'pen')} ${num(tool.width)} mm${tuned ? ' · changed here' : ''}</summary>
        <div class="grid">${fields}</div>${tuned ? '<button class="icon" data-act="reset" title="Back to the pen library / tools.toml">↺ undo tuning</button>' : ''}</details>
    </div>`;
  }).join('');
  $('#tools').innerHTML = head + cards;
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
  if (el.dataset.d === 'pen') {
    const colors = Object.values((S.pens[el.value] || {}).colors || {});
    const d = drafts[t];
    return redraft(t, { pen: el.value, color: colors.map((c) => c.toLowerCase()).includes(d.color.toLowerCase()) ? d.color : (colors[0] || d.color) });
  }
  if (el.dataset.d === 'color') return redraft(t, { color: el.value });
  if (el.dataset.d === 'name') { Object.assign(drafts[t], { name: el.value.trim(), named: !!el.value.trim() }); return renderTools(); }
  if (!el.dataset.k) return;
  setState(await api('PATCH', '/api/job', { tool_overrides: { [t]: { [el.dataset.k]: el.value === '' ? null : +el.value } } }));
});
$('#tools').addEventListener('click', async (e) => {
  const el = e.target;
  if (el.dataset.act === 'scan') {
    if (!confirm('Scan: take each tool to the tag reader in turn and read its tag?')) return;
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
    if (!confirm(`Dock ${t} (holder ${holder}), write ${what} onto its tag, and put it back?`)) return;
    const r = await api('POST', `/api/holders/${holder}/tag`, { pen: d.pen, color: d.color, name: d.name || suggestName(d.pen, d.color) });
    printer = { ...(printer || {}), job: r.job };
    renderTools(); watchJob();
  } else if (el.dataset.act === 'reset') {
    const keys = Object.fromEntries(Object.keys(S.job.tool_overrides[t] || {}).map((k) => [k, null]));
    setState(await api('PATCH', '/api/job', { tool_overrides: { [t]: keys } }));
  }
});
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
  $('#fonts').innerHTML = S.fonts.map((f) => `
    <li><span class="name" title="${esc(f.file)}">${esc(f.family)} <span class="note">${esc(f.style)} · ${f.kind === 'line' ? 'line' : 'source'}</span></span>
    <button class="icon" data-del="${esc(f.file)}" title="Remove">✕</button></li>`).join('') || '<li class="note">No fonts uploaded: texts use line fonts.</li>';
}
$('#fonts').addEventListener('click', async (e) => {
  const f = e.target.dataset.del;
  if (f && confirm(`Remove the font ${f}?`)) setState(await api('DELETE', `/api/fonts/${encodeURIComponent(f)}`));
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
  if (printer.tools_changed) setState(await api('GET', '/api/state'));
  else if (S) renderTools();
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
      setState(await api('PATCH', '/api/job', { machine_overrides: { bed_id: bed || null } }));
      toast(`Bed from Klipper: ${bed || 'none'}`);
    }
  }
  renderPrinter();
}
function renderPrinter() {
  const p = printer;
  if (!p) return;
  $('#printer').innerHTML = p.ok ? `
    <label>State</label><div>${esc(p.state)}${p.file ? ' · ' + esc(p.file) : ''}</div>
    <label>Bed</label><div>${esc(p.bed ?? '?')}</div>
    <label>Tools home</label><div>${p.occupied ? esc(p.occupied.join(', ')) || 'none' : '?'}</div>
    <label>Homed</label><div>${esc(p.homed || 'no')}</div>
    <label>At</label><div class="mono note">${esc(p.url)}</div>`
    : `<div class="full note">Can't reach Moonraker at ${esc(p.url || '?')}: ${esc(p.error || '')}</div>`;
}
async function send(start) {
  if (start && !confirm('Send this plot to Klipper and start it?')) return;
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
    toast(`${r.id} added`);
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
  renderObjects();
}
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

window.addEventListener('keydown', async (e) => {
  if (e.target.closest && e.target.closest('input, select, textarea')) return;
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  if (mod && key === 'z') { e.preventDefault(); return undo(e.shiftKey); }
  if (mod && key === 'y') { e.preventDefault(); return undo(true); }
  if (e.key === ' ') { spaceDown = true; svg.classList.add('pan-mode'); e.preventDefault(); return; }
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
  if (key === 'v') return setMode('select');
  if (key === 'h') return setMode('pan');
  if (key === 'p') return setMode('paint');
  if (key === 'f') return fit();
  if (key === '+' || key === '=') return zoom(0.8);
  if (key === '-') return zoom(1.25);
  const o = sel && obj(sel);
  if (!o) return;
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
  renderTools();
  renderFonts();
  renderOutput();
}

(async function start() {
  S = await api('GET', '/api/state');
  fit();
  setView(view);
  setState(S);
  pollPrinter();
  setInterval(() => { if (!document.hidden) pollPrinter(); }, 5000);
})();
