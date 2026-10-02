// Limn plot - the LED matrix UI (a Unicorn pHAT, 8 x 4, Klipper's `neopixel picam`) and
// the dock strip (`indockator`), as they shine now: /api/printer/leds has their colours
// (and the states ext/limn/leds.py set, with a new enough Klipper). Asked for a few
// times a second while the Display panel is open and the page is seen.
//
//   1  2 |  3 |  4  5  6 |  7 |  8        1 2 9 10      alert: the machine's mood
//   9 10 | 11 | 12 13 14 | 15 | 16        3 11 19       X Y Z endstops
//  17 18 | 19 | 20 21 22 | 23 | 24        27            K: the toolchanger's key, locked
//  25 26 | 27 | 28 29 30 | 31 | 32        17 18 25 26   tag; cols 4-6 a tool's number;
//                                         16 24 32      tool change: red, yellow, green
'use strict';

const LED_REGIONS = [
  { leds: [1, 2, 9, 10], name: 'Alert', what: 'The machine\'s mood: green fine, blue busy, amber look here, red stop; faster is fresher' },
  { leds: [3], name: 'X', what: 'X endstop' }, { leds: [11], name: 'Y', what: 'Y endstop' }, { leds: [19], name: 'Z', what: 'Z endstop' },
  { leds: [27], name: 'K', what: 'The toolchanger\'s key: red locked, green open' },
  { leds: [17, 18, 25, 26], name: 'Tag', what: 'The tag reader: reading, read, failed; a pen held to it by hand' },
  { leds: [4, 5, 6, 12, 13, 14, 20, 21, 22, 28, 29, 30], name: 'Tool', what: 'The carried tool\'s number (T0 is holder 41), or one drying out' },
  { leds: [16, 24, 32], name: 'Change', what: 'A tool change: red travelling, yellow at the holder, green leaving / done; red blinking: failed' },
];
const LED_STATES = {
  ui_alert: {
    error_new: 'a check failed, or the holders can\'t be read', error: 'a check failed, or the holders can\'t be read',
    drying_1: 'a pen is drying out', drying_2: 'a pen is drying out, longer', drying_3: 'a pen is drying out: cap it',
    busy_approach: 'tool change: travelling', busy_engage: 'tool change: at the holder', busy_leave: 'tool change: leaving',
    reading: 'reading or writing a tag', success: 'a tool change just went well',
    attention_fast: 'a hand was on the holders', attention: 'a hand was on the holders', attention_slow: 'a hand was on the holders',
    warn: 'a tool is unaccounted for, or the carried tool\'s tag failed', ready: 'carrying a tool, its tag read: ready', ok: 'all tools home',
  },
  ui_tag: {
    reading: 'reading', ok: 'read', error: 'failed', listening: 'listening for a pen held to it',
    scanned: 'a pen was scanned: into its holder now', taken: 'a holder took the scanned pen', late: 'the scanned pen went in too late',
  },
};
const DOCK_SEGMENTS = [[41, 1, 4], [42, 6, 10], [43, 13, 17], [44, 20, 23], [45, 26, 30]];

let ledTimer = null;
let ledData = null;

// LEDs are dim on purpose; on a screen, lift the dark end so a dim state still shows
const ledColour = ([r, g, b]) => {
  const k = (v) => Math.round(255 * Math.min(1, Math.pow(Math.max(v, 0), 0.55) * 1.15));
  return r + g + b < 0.004 ? null : `rgb(${k(r)}, ${k(g)}, ${k(b)})`;
};

function ledMatrixSvg(ui) {
  let cells = '';
  for (let i = 0; i < 32; i++) {
    const c = ui && ui[i] ? ledColour(ui[i]) : null, x = (i % 8) * 40, y = Math.floor(i / 8) * 40;
    const region = LED_REGIONS.find((r) => r.leds.includes(i + 1));
    cells += `<rect class="led${c ? ' lit' : ''}" x="${x + 4}" y="${y + 4}" width="32" height="32" rx="5"${c ? ` style="fill:${c};--glow:${c}"` : ''}>
      <title>${i + 1}${region ? ` · ${region.name}: ${region.what}` : ''}</title></rect>`;
  }
  return `<svg class="ledmatrix" viewBox="0 0 320 160" role="img" aria-label="The LED matrix UI, live">
    <rect width="320" height="160" rx="8" class="ledbg"/>${cells}
    <image href="/static/led-labels.svg" x="0" y="0" width="320" height="160" class="ledlabels"/></svg>`;
}

function dockStripSvg(dock) {
  if (!dock || !dock.length) return '';
  let out = '';
  for (let i = 0; i < dock.length; i++) {
    const c = ledColour(dock[i]);
    out += `<rect class="led${c ? ' lit' : ''}" x="${i * 10 + 1}" y="1" width="8" height="8" rx="2"${c ? ` style="fill:${c}"` : ''}/>`;
  }
  const labels = DOCK_SEGMENTS.map(([h, a, b]) => `<text x="${((a + b) / 2 - 1) * 10 + 5}" y="20">T${h - 41}</text>`).join('');
  return `<svg class="dockstrip" viewBox="0 0 ${dock.length * 10} 24" role="img" aria-label="The dock strip, live">${out}${labels}</svg>`;
}

function ledLegend(states) {
  if (!states) return '<p class="note">States show with a Klipper that has the limn extension of 2026-10-01 or later; the colours are live.</p>';
  const rows = [];
  if (states.ui_alert) rows.push(['Alert', LED_STATES.ui_alert[states.ui_alert] || states.ui_alert]);
  const tool = Object.entries(states).find(([k]) => k.startsWith('ui_tool_'));
  if (tool) rows.push(['Tool', `T${+tool[0].slice(8) - 41} ${tool[1].replace('_', ' ')}`]);
  if (states.ui_tag) rows.push(['Tag', LED_STATES.ui_tag[states.ui_tag] || states.ui_tag]);
  const phase = ['red', 'yellow', 'green'].map((c) => states[`ui_traffic_${c}`] && `${c} ${states[`ui_traffic_${c}`]}`).filter(Boolean);
  if (phase.length) rows.push(['Change', phase.join(', ')]);
  return `<dl class="ledlegend">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`;
}

function renderLeds() {
  const P = $('#leds');
  if (!P) return;
  if (!ledData || !ledData.ok) {
    P.innerHTML = (ledData && ledData.error) ? `<p class="note" title="${esc(ledData.error)}">No LEDs: Klipper doesn't answer.</p>`
      : '<p class="note">Asking Klipper…</p>';
    return;
  }
  const shape = `${(ledData.ui || []).length}/${(ledData.dock || []).length}`;
  if (P.dataset.shape !== shape) {                  // built once; then only the colours change
    P.dataset.shape = shape;
    P.innerHTML = ledMatrixSvg(ledData.ui) + dockStripSvg(ledData.dock) + '<div class="ledlegend-box"></div>';
  } else {
    const paint = (sel, list) => $$(sel, P).forEach((el, i) => {
      const c = list && list[i] ? ledColour(list[i]) : null;
      el.classList.toggle('lit', !!c);
      el.style.fill = c || '';
      el.style.setProperty('--glow', c || 'transparent');
    });
    paint('.ledmatrix rect.led', ledData.ui);
    paint('.dockstrip rect.led', ledData.dock);
  }
  const legend = ledLegend(ledData.states), box = $('.ledlegend-box', P);
  if (box.dataset.was !== legend) { box.dataset.was = legend; box.innerHTML = legend; }
}

function ledsShown() {
  const sec = $('#leds') && $('#leds').closest('section');
  return !!sec && !document.hidden && sec.offsetParent !== null && !sec.classList.contains('collapsed');
}
async function pollLeds() {
  clearTimeout(ledTimer);
  if (!ledsShown()) { ledTimer = setTimeout(pollLeds, 1500); return; }
  try {
    const r = await fetch('/api/printer/leds');
    ledData = r.ok ? await r.json() : { ok: false, error: r.statusText };
  } catch (e) { ledData = { ok: false, error: 'no answer' }; }
  renderLeds();
  ledTimer = setTimeout(pollLeds, 250);
}
document.addEventListener('visibilitychange', pollLeds);
pollLeds();
