// Limn plot - panels and windows over the canvas (the canvas is the whole page).
//
// Each <section data-panel> of the two docks becomes a card: its header collapses it
// (a tap), its grip moves it (a drag): to the other dock, to another place in one, or
// out over the canvas where it floats. data-fixed ones stay (the drawings, the
// captures); data-collapsed ones start folded. The scan viewer and the cameras are
// windows: moved by their bar, resized by their corner. Where everything is lives in
// this browser (store 'layout'); *Panels* hides them all (or \) and puts them back
// where they started. --dock-l, --dock-r, --top tell the canvas's tools what is free.
//
// On a phone (narrow) there is no room to float: the canvas takes the top of the page
// and the panels follow it, one column, scrolled like a page; a header only folds.
'use strict';

const LAYOUT_VERSION = 2;           // 2: the panels' order of 2026-10-02 (the printer's together)
const narrow = matchMedia('(max-width: 760px)');
const isNarrow = () => narrow.matches;
const layout = (() => {
  const l = store.get('layout', null);
  return l && l.v === LAYOUT_VERSION ? l : { v: LAYOUT_VERSION, panels: {}, windows: {} };
})();
const saveLayout = () => store.set('layout', layout);
const docks = { left: $('#left'), right: $('#right') };
const home = {};                            // panel -> {dock, order} as the page has it
const INTERACTIVE = 'button, input, select, textarea, a, label, summary';

function where(p) {
  const n = p.dataset.panel;
  return { ...home[n], collapsed: p.hasAttribute('data-collapsed'), ...(layout.panels[n] || {}) };
}
function setWhere(p, w) {
  layout.panels[p.dataset.panel] = { ...where(p), ...w };
  saveLayout();
}

function makePanel(sec, dock, order) {
  home[sec.dataset.panel] = { dock, order };
  const head = document.createElement('div'), body = document.createElement('div');
  head.className = 'phead';
  body.className = 'pbody';
  const h2 = $(':scope > h2', sec);
  while (sec.firstChild) {
    const n = sec.firstChild;
    (n === h2 ? head : body).append(n);
  }
  if (!sec.hasAttribute('data-fixed')) {
    head.insertAdjacentHTML('afterbegin', '<span class="grip" aria-hidden="true" title="Drag to move it: to the other side, or out over the canvas">⠿</span>');
  }
  head.insertAdjacentHTML('beforeend', '<button class="pcollapse icon" title="Fold or unfold (or tap the header)" aria-label="Fold">▾</button>');
  sec.append(head, body);
  sec.classList.add('panel');
}

function applyLayout() {
  const panels = $$('section[data-panel]');
  // narrow: a floating one goes back to its dock (where it is kept for a wide screen)
  const dockOf = (p) => (where(p).dock === 'float' && isNarrow() ? home[p.dataset.panel].dock : where(p).dock);
  for (const side of ['left', 'right']) {
    panels.filter((p) => dockOf(p) === side).sort((a, b) => where(a).order - where(b).order)
      .forEach((p) => { p.classList.remove('floating'); p.style.left = p.style.top = p.style.width = ''; docks[side].append(p); });
  }
  for (const p of panels.filter((p) => dockOf(p) === 'float')) {
    const w = where(p);
    p.classList.add('floating');
    p.style.width = `${Math.max(240, w.w || 290)}px`;
    p.style.left = `${Math.min(Math.max(0, w.x || 0), innerWidth - 120)}px`;
    p.style.top = `${Math.min(Math.max(0, w.y || 60), innerHeight - 60)}px`;
    $('#floats').append(p);
  }
  panels.forEach((p) => p.classList.toggle('collapsed', !!where(p).collapsed));
  insets();
}

// How much of the canvas the docks take, for the canvas's own tools
let insetsWere = '';
function insets() {
  if (isNarrow()) {                         // the panels are under the canvas, not over it
    const now = 'narrow';
    if (now === insetsWere) return;
    insetsWere = now;
    const st = document.documentElement.style;
    st.setProperty('--dock-l', '0px'); st.setProperty('--dock-r', '0px'); st.setProperty('--top', '0px');
    if (typeof drawRulers === 'function') requestAnimationFrame(drawRulers);
    return;
  }
  const bare = document.body.classList.contains('bare');
  const shown = (d) => !bare && $$(':scope > section[data-panel]', d).some((p) => p.offsetParent !== null);
  const L = shown(docks.left) ? docks.left.getBoundingClientRect().right + 8 : 8;
  const R = shown(docks.right) ? innerWidth - docks.right.getBoundingClientRect().left + 8 : 8;
  const top = ($('.topbar').getBoundingClientRect().bottom || 0) + 8;
  const now = `${L}/${R}/${top}`;
  if (now === insetsWere) return;
  insetsWere = now;
  const st = document.documentElement.style;
  st.setProperty('--dock-l', `${Math.round(L)}px`);
  st.setProperty('--dock-r', `${Math.round(R)}px`);
  st.setProperty('--top', `${Math.round(top)}px`);
  if (typeof drawRulers === 'function') requestAnimationFrame(drawRulers);
}

// A tap on a header folds the panel; a drag on it moves the panel
let pdrag = null;
document.addEventListener('pointerdown', (e) => {
  const head = e.target.closest('.phead');
  if (!head || e.button !== 0) return;
  if (e.target.closest(INTERACTIVE) && !e.target.closest('.pcollapse')) return;
  const p = head.closest('section[data-panel]');
  pdrag = { p, head, sx: e.clientX, sy: e.clientY, id: e.pointerId, started: false,
            fold: !!e.target.closest('.pcollapse'), fixed: p.hasAttribute('data-fixed') };
});
document.addEventListener('pointermove', (e) => {
  if (!pdrag || e.pointerId !== pdrag.id) return;
  const { p } = pdrag;
  if (!pdrag.started) {
    if (Math.hypot(e.clientX - pdrag.sx, e.clientY - pdrag.sy) < 6) return;
    if (pdrag.fixed || isNarrow()) { pdrag.swiped = true; return; }       // a swipe: the page scrolls
    const r = p.getBoundingClientRect();
    pdrag.started = true;
    pdrag.dx = e.clientX - r.left;
    pdrag.dy = e.clientY - r.top;
    pdrag.w = r.width;
    p.classList.add('dragging', 'floating');
    p.style.width = `${r.width}px`;
    $('#floats').append(p);
    try { pdrag.head.setPointerCapture(pdrag.id); } catch { /* not a real pointer */ }
    insets();
  }
  p.style.left = `${e.clientX - pdrag.dx}px`;
  p.style.top = `${e.clientY - pdrag.dy}px`;
  showDrop(dropTarget(e));
});
document.addEventListener('pointerup', (e) => {
  if (!pdrag || e.pointerId !== pdrag.id) return;
  const d = pdrag;
  pdrag = null;
  if (!d.started) {                         // a tap: fold or unfold
    if (d.swiped || (e.target.closest(INTERACTIVE) && !d.fold)) return;
    setWhere(d.p, { collapsed: !where(d.p).collapsed });
    d.p.classList.toggle('collapsed', where(d.p).collapsed);
    insets();
    return;
  }
  d.p.classList.remove('dragging');
  const t = dropTarget(e);
  showDrop(null);
  if (t.dock === 'float') {
    setWhere(d.p, { dock: 'float', x: e.clientX - d.dx, y: e.clientY - d.dy, w: d.w });
  } else {
    // Its place among the others of that dock: before the one under the pointer
    const others = $$(':scope > section[data-panel]', docks[t.dock]).filter((x) => x !== d.p);
    others.splice(t.index, 0, d.p);
    others.forEach((x, i) => { layout.panels[x.dataset.panel] = { ...where(x), dock: t.dock, order: i }; });
    saveLayout();
  }
  applyLayout();
});

document.addEventListener('pointercancel', (e) => { if (pdrag && e.pointerId === pdrag.id && !pdrag.started) pdrag = null; });

function dropTarget(e) {
  const lr = docks.left.getBoundingClientRect(), rr = docks.right.getBoundingClientRect();
  const dock = e.clientX < lr.right + 24 ? 'left' : e.clientX > rr.left - 24 ? 'right' : 'float';
  if (dock === 'float') return { dock };
  const ps = $$(':scope > section[data-panel]', docks[dock]).filter((p) => p.offsetParent !== null && !p.classList.contains('dragging'));
  let index = ps.length;
  for (let i = 0; i < ps.length; i++) {
    const r = ps[i].getBoundingClientRect();
    if (e.clientY < r.top + r.height / 2) { index = i; break; }
  }
  const all = $$(':scope > section[data-panel]', docks[dock]).filter((p) => !p.classList.contains('dragging'));
  return { dock, index: index < ps.length ? all.indexOf(ps[index]) : all.length, before: ps[index] || null };
}
let dropLine = null;
function showDrop(t) {
  if (!dropLine) { dropLine = document.createElement('div'); dropLine.className = 'dropline'; }
  if (!t || t.dock === 'float') { dropLine.remove(); return; }
  t.before ? docks[t.dock].insertBefore(dropLine, t.before) : docks[t.dock].append(dropLine);
}

// Windows: the scan viewer and the cameras, moved by their bar, resized by their corner
function makeWindow(content, key) {
  const win = document.createElement('div');
  win.className = 'win';
  win.dataset.win = key;
  content.parentNode.insertBefore(win, content);
  win.append(content);
  win.insertAdjacentHTML('beforeend', '<span class="wresize" title="Drag to resize" aria-hidden="true"></span>');
  const place = () => {
    const g = layout.windows[key];
    win.classList.toggle('placed', !!g);
    if (!g) { win.style.left = win.style.top = win.style.width = win.style.height = ''; return; }
    win.style.left = `${Math.min(Math.max(0, g.x), innerWidth - 120)}px`;
    win.style.top = `${Math.min(Math.max(0, g.y), innerHeight - 60)}px`;
    win.style.width = `${g.w}px`;
    win.style.height = `${g.h}px`;
  };
  place();
  let wd = null;
  win.addEventListener('pointerdown', (e) => {
    const resize = e.target.closest('.wresize');
    const bar = e.target.closest('.vbar');
    if (e.button !== 0 || (!resize && (!bar || e.target.closest(INTERACTIVE)))) return;
    const r = win.getBoundingClientRect();
    wd = { resize: !!resize, sx: e.clientX, sy: e.clientY, r, id: e.pointerId };
    try { win.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ }
    e.preventDefault();
  });
  win.addEventListener('pointermove', (e) => {
    if (!wd || e.pointerId !== wd.id) return;
    const dx = e.clientX - wd.sx, dy = e.clientY - wd.sy, r = wd.r;
    layout.windows[key] = wd.resize
      ? { x: r.left, y: r.top, w: Math.max(280, r.width + dx), h: Math.max(160, r.height + dy) }
      : { x: r.left + dx, y: r.top + dy, w: r.width, h: r.height };
    place();
  });
  win.addEventListener('pointerup', () => { if (wd) { wd = null; saveLayout(); } });
  win.addEventListener('dblclick', (e) => {          // the bar, twice: back where it starts
    if (!e.target.closest('.vbar') || e.target.closest(INTERACTIVE)) return;
    delete layout.windows[key];
    saveLayout();
    place();
  });
  return { place };
}

// *Panels*: hide them all, or put everything back where it started
function setBare(on) {
  document.body.classList.toggle('bare', on);
  $('#layout-button').classList.toggle('on', on);
  insetsWere = '';
  insets();
}
$('#layout-button').addEventListener('click', (e) => {
  if (e.shiftKey || e.altKey) return resetLayout();
  setBare(!document.body.classList.contains('bare'));
});
$('#layout-button').addEventListener('contextmenu', (e) => { e.preventDefault(); resetLayout(); });
function resetLayout() {
  if (!twice('layout-reset', $('#layout-button'), 'Put every panel and window back where it started')) return;
  layout.panels = {};
  layout.windows = {};
  saveLayout();
  applyLayout();
  windows.forEach((w) => w.place());
  toast('Panels back where they started');
}
window.addEventListener('keydown', (e) => {
  if (e.key !== '\\' || e.target.closest('input, select, textarea')) return;
  setBare(!document.body.classList.contains('bare'));
});

for (const side of ['left', 'right']) {
  $$(':scope > section[data-panel]', docks[side]).forEach((sec, i) => makePanel(sec, side, i));
}
const windows = [makeWindow($('#viewer'), 'viewer'), makeWindow($('#cams'), 'cams')];
applyLayout();
// The docks' contents change with the tab and as panels show and hide
new MutationObserver(() => requestAnimationFrame(insets)).observe(document.body, { attributes: true, attributeFilter: ['class'] });
for (const d of Object.values(docks)) new MutationObserver(() => requestAnimationFrame(insets)).observe(d, { attributes: true, subtree: true, attributeFilter: ['hidden'] });
window.addEventListener('resize', () => { insetsWere = ''; insets(); });
narrow.addEventListener('change', () => {
  insetsWere = '';
  applyLayout();
  windows.forEach((w) => w.place());
  if (typeof fit === 'function' && S) requestAnimationFrame(fit);
});
