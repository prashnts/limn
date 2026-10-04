// Limn plot - the head on the canvas: where Klipper says it is (/api/printer/position),
// the toolhead from above (/api/toolhead.svg, mm, the tool point at its origin), a
// crosshair at the carried tool's tip, and on the Scan tab, with the camera on the
// carriage, what the camera sees now. Asked for often while it moves, less when it
// is still, not at all with *head* off or the page hidden.
'use strict';

let headSvg = null;             // {href, box: [x, y, w, h]}: the outline's viewBox, mm
let headPos = null;             // /api/printer/position
let headTimer = null;

async function loadHeadSvg() {
  try {
    const text = await (await fetch('/api/toolhead.svg')).text();
    const vb = /viewBox="([^"]+)"/.exec(text)[1].trim().split(/[\s,]+/).map(Number);
    headSvg = { href: `/api/toolhead.svg?t=${Date.now()}`, box: vb };
  } catch { headSvg = null; }
}
const headOn = () => $('#show-head').checked;

async function pollHead() {
  clearTimeout(headTimer);
  if (!headOn() || document.hidden) { drawHead(); return; }
  const was = headPos && headPos.head;
  try {
    const r = await fetch('/api/printer/position');
    headPos = r.ok ? await r.json() : null;
  } catch { headPos = null; }
  drawHead();
  const now = headPos && headPos.head;
  const moving = was && now && Math.hypot(now[0] - was[0], now[1] - was[1]) > 0.01;
  headTimer = setTimeout(pollHead, moving ? 250 : 800);
}

function cameraCarried() {
  // On the Scan tab: the camera tool's holder is empty, so the camera is on the carriage
  if (typeof cam !== 'function' || !document.body.classList.contains('tab-scan')) return null;
  const c = cam();
  if (c && c.fixed) return c;                 // the endoscope: always there
  if (!c || !printer || !printer.ok || !Array.isArray(printer.occupied)) return null;
  return printer.occupied.map(String).includes(String(c.holder)) ? null : c;
}

function drawHead() {
  const L = $('#head-layer');
  L.innerHTML = '';
  if (!headOn() || !headPos || !headPos.ok || !headPos.head) return;
  const [x, y, z] = headPos.head, [tx, ty] = headPos.tip;
  if (headSvg) {
    const [bx, by, bw, bh] = headSvg.box;
    const g = svgEl('g', { class: 'head-outline', transform: `translate(${x} ${y}) scale(1,-1)` }, L);
    svgEl('image', { href: headSvg.href, x: bx, y: by, width: bw, height: bh }, g);
  }
  const c = cameraCarried();
  if (c) {
    const [fx, fy] = footprint(c.fov, c.turn || 0), [cx, cy] = c.center || [0, 0];
    svgEl('rect', { class: 'head-view', x: tx + cx - fx / 2, y: ty + cy - fy / 2, width: fx, height: fy }, L);
  }
  const s = mmPerPx();            // the crosshair keeps its size on the screen
  const r = 9 * s;
  svgEl('line', { class: 'head-cross', x1: tx - r, x2: tx + r, y1: ty, y2: ty }, L);
  svgEl('line', { class: 'head-cross', x1: tx, x2: tx, y1: ty - r, y2: ty + r }, L);
  svgEl('circle', { class: 'head-cross', cx: tx, cy: ty, r: 3.5 * s }, L);
  const label = svgEl('text', { class: 'head-label', x: tx + 11 * s, y: -(ty + 11 * s), transform: 'scale(1,-1)', 'font-size': 11 * s }, L);
  label.textContent = `X ${num(tx, 2)} Y ${num(ty, 2)} Z ${num(z, 2)}`;
}

$('#show-head').checked = store.get('showHead', true);
$('#show-head').addEventListener('change', () => { store.set('showHead', $('#show-head').checked); pollHead(); });
document.addEventListener('visibilitychange', pollHead);
loadHeadSvg().then(pollHead);
