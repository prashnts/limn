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
//
// Tabs, as in a slicer: each dock shows one group of its panels at a time (GROUPS; *All*:
// every one, as before). A panel moved to the other dock takes its group's tab with it;
// one moved out over the canvas leaves its title behind (a stub: a tap puts it back).
// Output is no dock's: it sits over the canvas at the bottom (#outbar), folded to a
// button, and unfolds upwards, or floats like the others. *Find a setting* (/) looks
// through every panel's settings and macro buttons, the tabs set aside while it does.
'use strict';

const LAYOUT_VERSION = 5;           // 3: the tabs of 2026-10-16 (tools, printer), Output over the canvas; 4: Drawing on Tools; 5: Paper
const narrow = matchMedia('(max-width: 760px)');
const isNarrow = () => narrow.matches;
const layout = (() => {
  const l = store.get('layout', null);
  return l && l.v === LAYOUT_VERSION ? l : { v: LAYOUT_VERSION, panels: {}, windows: {} };
})();
const saveLayout = () => store.set('layout', layout);
// Each panel's tab; one not here (output) is pinned: in a dock, under the tabs, always there
const GROUPS = {
  drawings: ['objects', 'Objects', 'The drawings on the bed, the selected one\'s place, layers, texts, masks'],
  drawing: ['objects'], paper: ['objects'], layers: ['layers', 'Layers', 'Each pen\'s layer over every drawing, in the order they plot'],
  captures: ['captures', 'Captures', 'Photos taken with the camera tool'],
  paint: ['paint', 'Paint', 'Paint shapes with a tool'],
  tools: ['tools', 'Tools', 'How every tool draws, the tools in the holders and the plan\'s pens, the pen library; the camera, its shots, the NAS'],
  drawset: ['tools'], pens: ['tools'], camera: ['tools'], shots: ['tools'], nas: ['tools'],
  printer: ['printer', 'Printer', 'Klipper and its macros, the plotter\'s settings for this job, the LED display, fonts'],
  machine: ['printer'], display: ['printer'], fonts: ['printer'],
};
const groupOf = (p) => (GROUPS[p.dataset.panel || p.dataset.of] || [null])[0];
const SIDES = ['left', 'right'];            // the docks with tabs; the bar (#outbar) has none
const groupInfo = (g) => Object.values(GROUPS).find((x) => x[0] === g && x[1]) || [g, g, ''];
layout.tabs = layout.tabs || {};
const docks = { left: $('#left'), right: $('#right'), bar: $('#outbar') };
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

// Unfold a panel (app.js: picking a shape shows its settings)
function unfoldPanel(name) {
  const p = $(`section[data-panel="${name}"]`);
  if (!p) return;
  const side = SIDES.find((k) => docks[k].contains(p));
  if (side && groupOf(p) && tabOf(side) !== 'all' && tabOf(side) !== groupOf(p)) setDockTab(side, groupOf(p));
  if (!where(p).collapsed) return;
  setWhere(p, { collapsed: false });
  p.classList.remove('collapsed');
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
  $$('.pstub').forEach((x) => x.remove());
  for (const side of [...SIDES, 'bar']) {
    // a floating one's title stays where it was (a stub), among the others in their order
    const stubs = isNarrow() ? [] : panels.filter((p) => dockOf(p) === 'float' && (where(p).from || home[p.dataset.panel].dock) === side).map(stubOf);
    [...panels.filter((p) => dockOf(p) === side), ...stubs].sort((a, b) => orderOf(a) - orderOf(b)).forEach((p) => {
      if (p.matches('section')) { p.classList.remove('floating'); p.style.left = p.style.top = p.style.width = ''; }
      docks[side].append(p);
    });
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
  for (const side of SIDES) {                     // pinned ones (output) under the tabs' panels
    $$(':scope > section[data-panel]', docks[side]).filter((p) => !groupOf(p)).forEach((p) => docks[side].append(p));
  }
  renderTabs();
  insets();
}
const orderOf = (x) => where(x.matches('section') ? x : $(`section[data-panel="${x.dataset.of}"]`)).order;
const titleOf = (p) => ($(':scope > .phead h2', p).firstChild?.nodeValue || p.dataset.panel).trim();
function stubOf(p) {
  const x = document.createElement('div');
  x.className = 'pstub';
  for (const c of ['plot-only', 'scan-only']) if (p.classList.contains(c)) x.classList.add(c);
  x.dataset.of = p.dataset.panel;
  x.title = `${titleOf(p)} is out over the canvas: tap to put it back here`;
  x.innerHTML = `<span class="pchev" aria-hidden="true">▸</span><h2>${titleOf(p)}</h2><span class="note">out</span>
    <button class="icon" aria-label="Put it back" title="Put it back here">↩</button>`;
  return x;
}
// A stub, tapped: its panel back where it was
document.addEventListener('click', (e) => {
  const x = e.target.closest('.pstub');
  if (!x) return;
  const p = $(`section[data-panel="${x.dataset.of}"]`);
  setWhere(p, { dock: where(p).from || home[p.dataset.panel].dock, from: undefined });
  applyLayout();
});

// The docks' tabs: the groups of the panels in a dock that the page's tab (Plot, Scan) shows
const tabBars = {}, dockHeads = {};
for (const side of SIDES) {
  const head = document.createElement('div'), bar = document.createElement('div');
  head.className = 'dhead';
  head.append(bar);
  dockHeads[side] = head;
  bar.className = 'dtabs';
  bar.setAttribute('role', 'tablist');
  bar.setAttribute('aria-label', side === 'left' ? 'Left panels' : 'Right panels');
  docks[side].prepend(head);
  tabBars[side] = bar;
  bar.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-dtab]');
    if (b) setDockTab(side, b.dataset.dtab);
  });
}
const pageTab = () => (document.body.classList.contains('tab-scan') ? 'scan' : 'plot');
const offTab = (p) => p.classList.contains(pageTab() === 'scan' ? 'plot-only' : 'scan-only');
function groupsIn(side) {
  const gs = [];
  for (const p of $$(':scope > section[data-panel], :scope > .pstub', docks[side])) {
    const g = groupOf(p);
    if (g && !offTab(p) && !gs.includes(g)) gs.push(g);
  }
  return gs;
}
function tabOf(side) {
  const gs = groupsIn(side), t = (layout.tabs[side] || {})[pageTab()];
  return t === 'all' || gs.includes(t) ? t : gs[0] || 'all';
}
function setDockTab(side, g) {
  layout.tabs[side] = { ...(layout.tabs[side] || {}), [pageTab()]: g };
  saveLayout();
  renderTabs();
  insetsWere = '';
  insets();
}
function renderTabs() {
  for (const side of SIDES) {
    const gs = groupsIn(side), on = tabOf(side), bar = tabBars[side];
    if (docks[side].firstElementChild !== dockHeads[side]) docks[side].prepend(dockHeads[side]);     // moving it would blur the find box
    bar.hidden = gs.length < 2;
    dockHeads[side].hidden = bar.hidden && !dockHeads[side].querySelector('.find');
    const want = [...gs.map((g) => { const [, label, help] = groupInfo(g); return [g, label, help]; }),
      ['all', 'All', 'Every panel of this side, one under the other']];
    const html = want.map(([g, label, help], i) => `<button role="tab" data-dtab="${g}" class="${g === on ? 'on' : ''}" aria-selected="${g === on}"
      title="${help}${i < 9 ? ` (Alt+${side === 'right' ? '' : 'Shift+'}${i + 1})` : ''}">${label}</button>`).join('');
    if (bar.dataset.html !== html) { bar.innerHTML = html; bar.dataset.html = html; }
    for (const p of $$(':scope > section[data-panel], :scope > .pstub', docks[side])) {
      p.classList.toggle('tab-off', !finding() && gs.length > 1 && on !== 'all' && !!groupOf(p) && groupOf(p) !== on);
    }
  }
}
// Alt+1..9: the right side's tabs, Alt+Shift+1..9: the left's
window.addEventListener('keydown', (e) => {
  if (!e.altKey || e.ctrlKey || e.metaKey || !/^Digit[1-9]$/.test(e.code) || isNarrow()) return;
  const side = e.shiftKey ? 'left' : 'right', bs = $$('button[data-dtab]', tabBars[side]), b = bs[+e.code.slice(5) - 1];
  if (!b || tabBars[side].hidden) return;
  e.preventDefault();
  setDockTab(side, b.dataset.dtab);
});

// Find a setting: the rows of the panels' forms whose label (or its hint) has the words
const findBox = document.createElement('div');
findBox.className = 'find';
findBox.innerHTML = `<input id="find-setting" type="search" placeholder="Find a setting…  /" aria-label="Find a setting"
  title="Look through every panel's settings and Klipper's macro buttons by name (/; Esc clears it)" autocomplete="off" spellcheck="false">`;
dockHeads.right.append(findBox);
const findInput = $('#find-setting', findBox);
const finding = () => !!findInput.value.trim();
const FIND_ROWS = '.form > label, .grid > label, #macros button';
function ownText(el) {
  let t = el.title || '';
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement.closest('option, select, .note') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
  while (walk.nextNode()) t += ' ' + walk.currentNode.nodeValue;
  for (const c of $$('[title]', el)) t += ' ' + c.title;
  return t.toLowerCase();
}
function runFind() {
  const words = findInput.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  document.body.classList.toggle('finding', !!words.length);
  $$('.find-miss, .find-hit, .find-all').forEach((x) => x.classList.remove('find-miss', 'find-hit', 'find-all'));
  renderTabs();
  if (!words.length) {                    // what it unfolded folds again
    findOpened.forEach((d) => { d.open = false; });
    findOpened.clear();
    insetsWere = '';
    insets();
    return;
  }
  const hit = (t) => words.every((w) => t.includes(w));
  for (const p of $$('section[data-panel]')) {
    if (offTab(p)) continue;
    if (hit(($(':scope > .phead h2', p).firstChild?.nodeValue || '').toLowerCase())) { p.classList.add('find-all'); continue; }  // its name: all of it
    let n = 0;
    for (const row of $$(FIND_ROWS, p)) {
      // a label and the control after it (a .form's two columns) go together; a macro button with its group's name
      const pair = row.matches('.form > label') && row.nextElementSibling && !row.nextElementSibling.matches('label:not(.check)') ? row.nextElementSibling : null;
      const group = row.closest('.mgroup');
      const ok = hit(ownText(row) + (pair ? ' ' + ownText(pair) : '') + (group ? ' ' + ownText($('.mlabel', group)) : ''));
      row.classList.toggle('find-hit', ok);
      if (pair) pair.classList.toggle('find-hit', ok);
      if (ok) {
        n++;
        for (let d = row.closest('details'); d; d = d.parentElement.closest('details')) {
          if (!d.open) { findOpened.add(d); d.open = true; }
        }
      }
    }
    p.classList.toggle('find-miss', !n);
  }
  insetsWere = '';
  insets();
}
let findPending = false;
const findOpened = new Set();
findInput.addEventListener('input', runFind);
findInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { findInput.value = ''; runFind(); findInput.blur(); e.stopPropagation(); }
  if (e.key === 'Enter') { const h = $('section.panel:not(.find-miss) .find-hit input, section.panel:not(.find-miss) .find-hit select, section.panel:not(.find-miss) button.find-hit'); if (h) h.focus(); }
});
window.addEventListener('keydown', (e) => {
  if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || e.target.closest('input, select, textarea')) return;
  e.preventDefault();
  findInput.focus();
  findInput.select();
});
// The panels redraw as the state changes: look again in what they show now
for (const d of Object.values(docks)) {
  new MutationObserver(() => {
    if (!finding() || findPending) return;
    findPending = true;
    requestAnimationFrame(() => { findPending = false; runFind(); });
  }).observe(d, { childList: true, subtree: true });
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
  // what scrolls into view in a dock keeps clear of the pinned Output under it
  for (const d of Object.values(docks)) {
    const pin = $$(':scope > section[data-panel]', d).find((p) => !groupOf(p) && p.offsetParent !== null);
    d.style.scrollPaddingBottom = pin ? `${Math.ceil(pin.getBoundingClientRect().height) + 8}px` : '';
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
  showDrop(dropTarget(e, p));
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
  const t = dropTarget(e, d.p);
  showDrop(null);
  if (t.dock === 'float') {
    const was = where(d.p);                 // where its stub stays
    setWhere(d.p, { dock: 'float', from: was.dock === 'float' ? was.from : was.dock, x: e.clientX - d.dx, y: e.clientY - d.dy, w: d.w });
  } else {
    // Its place among the others of that dock: before the one under the pointer
    const others = $$(':scope > section[data-panel]', docks[t.dock]).filter((x) => x !== d.p);
    others.splice(t.index, 0, d.p);
    others.forEach((x, i) => { layout.panels[x.dataset.panel] = { ...where(x), dock: t.dock, order: i }; });
    // its dock shows its tab, or it would vanish where it was dropped
    if (SIDES.includes(t.dock) && groupOf(d.p) && (layout.tabs[t.dock] || {})[pageTab()] !== 'all') layout.tabs[t.dock] = { ...(layout.tabs[t.dock] || {}), [pageTab()]: groupOf(d.p) };
    saveLayout();
  }
  applyLayout();
});

document.addEventListener('pointercancel', (e) => { if (pdrag && e.pointerId === pdrag.id && !pdrag.started) pdrag = null; });

function dropTarget(e, p) {
  const lr = docks.left.getBoundingClientRect(), rr = docks.right.getBoundingClientRect();
  const dock = e.clientX < lr.right + 24 ? 'left' : e.clientX > rr.left - 24 ? 'right' : 'float';
  // Output's own place: the bottom of the canvas, over the scrubber
  if (dock === 'float' && p && p.dataset.panel === 'output' && e.clientY > innerHeight - 160) return { dock: 'bar', index: 0, before: null };
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
  docks.bar.classList.toggle('drop-here', !!t && t.dock === 'bar');
  if (!t || t.dock === 'float' || t.dock === 'bar') { dropLine.remove(); return; }
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

for (const side of [...SIDES, 'bar']) {
  $$(':scope > section[data-panel]', docks[side]).forEach((sec, i) => makePanel(sec, side, i));
}
const windows = [makeWindow($('#viewer'), 'viewer'), makeWindow($('#cams'), 'cams')];
applyLayout();
// The docks' contents change with the tab and as panels show and hide
let pageTabWas = pageTab();
new MutationObserver(() => {
  if (pageTab() !== pageTabWas) { pageTabWas = pageTab(); renderTabs(); if (finding()) runFind(); }
  requestAnimationFrame(insets);
}).observe(document.body, { attributes: true, attributeFilter: ['class'] });
for (const d of Object.values(docks)) new MutationObserver(() => requestAnimationFrame(insets)).observe(d, { attributes: true, subtree: true, attributeFilter: ['hidden'] });
window.addEventListener('resize', () => { insetsWere = ''; insets(); });
narrow.addEventListener('change', () => {
  insetsWere = '';
  applyLayout();
  windows.forEach((w) => w.place());
  if (typeof fit === 'function' && S) requestAnimationFrame(fit);
});
