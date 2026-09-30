// Limn plot - the Scan tab: the camera tool photographs a region of the bed,
// focused by height, and the photos are kept on the server to browse. The
// server does the moving and the shooting (/api/camera, limn_cam/scan.py);
// this draws the region and the tiles on the bed, and shows what came back.
// It uses app.js's globals: S, api, fill, quietly, svgEl, worldPt, $, $$ ..
'use strict';

let C = null;                   // /api/camera: settings, cameras, job, captures
let smode = 'region';           // region | pan | look | focus
let sdrag = null;               // a region being drawn
let viewing = null;             // {meta, info, view: 'stitch'|'tiles'|file, ppm}
let camTimer = null;

const scanTab = () => document.body.classList.contains('tab-scan');

// --- the ribbon ------------------------------------------------------------------
function setTab(t) {
  store.set('tab', t);
  document.body.classList.toggle('tab-scan', t === 'scan');
  document.body.classList.toggle('tab-plot', t !== 'scan');
  $$('#ribbon [data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === t));
  if (t === 'scan') loadCamera();
  else closeViewer();
  drawScanLayer();
  drawUnder();
}
$('#ribbon').addEventListener('click', (e) => {
  const b = e.target.closest('[data-tab]');
  if (b) setTab(b.dataset.tab);
});

// --- state from the server ------------------------------------------------------------
async function loadCamera(background = false) {
  try {
    C = await api('GET', '/api/camera');
  } catch {
    return;
  }
  const draw = () => { renderCamera(); renderJob(); renderCaptures(); };
  background ? quietly(draw) : draw();
  drawScanLayer();
  clearTimeout(camTimer);
  const busy = C.job && !C.job.done;
  if (scanTab()) camTimer = setTimeout(() => loadCamera(true), busy ? 1000 : 5000);
}
async function patchScan(body) {
  C = await api('PATCH', '/api/camera', body);
  renderCamera(); renderJob(); drawScanLayer();
}
const cam = () => C && (C.cameras[C.settings.tool] || Object.values(C.cameras)[0]);
const focusZ = () => (C.settings.z ?? (cam() || {}).focus_z ?? 7.5);
function sweepOf(c) {        // as limn_cam/scan.py Job.sweep(): unset, clear_z down 2.5
  const [lo] = c.z_limits;
  return C.settings.sweep || [Math.max(lo, c.clear_z - 2.5), c.clear_z, 0.25];
}

// Same as limn_cam/scan.py tiles()
function footprint(fov, turn) {
  const [w, h] = fov, c = Math.abs(Math.cos(turn * Math.PI / 180)), s = Math.abs(Math.sin(turn * Math.PI / 180));
  return [w * c + h * s, w * s + h * c];
}
function scanTiles() {
  const c = cam(), r = C && C.settings.region;
  if (!c || !r) return [];
  const [fx, fy] = footprint(c.fov, c.turn || 0), ov = C.settings.overlap;
  const centres = (a, b, f) => {
    const span = b - a;
    if (span <= f) return [(a + b) / 2];
    const n = Math.ceil((span - f) / (f * (1 - ov))) + 1;
    return Array.from({ length: n }, (_, i) => a + f / 2 + i * (span - f) / (n - 1));
  };
  const xs = centres(r[0], r[2], fx), ys = centres(r[1], r[3], fy), out = [];
  ys.forEach((y, ri) => (ri % 2 ? [...xs].reverse() : xs).forEach((x) => out.push([x, y])));
  return out;
}

// --- the camera panel ------------------------------------------------------------------
const fld = (k, label, value, attrs, help) => `<label for="s-${k}" title="${esc(help)}">${label}</label>
  <input id="s-${k}" data-s="${k}" type="number" value="${value ?? ''}" ${attrs} title="${esc(help)}">`;
function renderCamera() {
  const P = $('#camera');
  if (!C || !S) return;
  const cams = Object.values(C.cameras);
  if (!cams.length) {
    const types = Object.entries(S.pens).filter(([, p]) => p.kind === 'camera');
    fill(P, `<p class="full note">No camera tool yet: its tag has to name a camera type. Pick the holder it is in
      and write it (the camera is docked, written and put back).</p>
      <label for="c-holder" title="The holder the camera tool is in">Holder</label>
      <select id="c-holder" title="The holder the camera tool is in">${S.holders.map((h) => opt(String(h.holder), '', `${h.t} (${h.holder})`)).join('')}</select>
      <label for="c-type" title="Camera types of the library (pens.toml, kind = camera)">Type</label>
      <select id="c-type" title="Camera types of the library (pens.toml, kind = camera)">${types.map(([k, p]) => opt(k, '', `${p.name} (${k})`)).join('') || '<option value="">none in the library</option>'}</select>
      <label for="c-name" title="The tag's name, up to 20 characters">Name</label>
      <input id="c-name" maxlength="20" value="${esc((types[0] && types[0][1].short) || 'Camera')}" title="The tag's name, up to 20 characters">
      <label></label><button data-act="write-cam" class="primary" title="Dock the tool, write the camera type onto its tag, put it back"${types.length ? '' : ' disabled'}>Write tag</button>`);
    return;
  }
  const c = cam(), s = C.settings, r = s.region || ['', '', '', ''];
  const [lo, hi] = c.z_limits, sw = sweepOf(c);
  const n = scanTiles().length;
  const per = (s.settle ?? c.settle) + 1.5 + (s.refocus > 0 ? (2 * s.refocus / s.refocus_step + 1) * 1.6 : 0);
  const [fx, fy] = footprint(c.fov, c.turn || 0);
  fill(P, `
    <label for="s-tool" title="Which camera tool takes the shots">Camera</label>
    <select id="s-tool" data-s="tool" title="Which camera tool takes the shots">${cams.map((t) => opt(t.id, c.id, `${t.id} ${t.name}`)).join('')}</select>
    <label title="What one shot covers at its focus height (fov in pens.toml)">One shot</label>
    <div class="mono note" title="What one shot covers at its focus height (fov in pens.toml)">${num(fx, 1)} × ${num(fy, 1)} mm</div>
    <label title="The region to scan, mm: drag on the bed with the Region tool (R), or type it">Region</label>
    <div class="row region" title="From x, y to x, y (mm)">
      <input data-s="r0" type="number" step="0.5" value="${num(r[0], 1)}" title="Region: from X (mm)">
      <input data-s="r1" type="number" step="0.5" value="${num(r[1], 1)}" title="Region: from Y (mm)">
      <input data-s="r2" type="number" step="0.5" value="${num(r[2], 1)}" title="Region: to X (mm)">
      <input data-s="r3" type="number" step="0.5" value="${num(r[3], 1)}" title="Region: to Y (mm)">
    </div>
    <label title="Heights are the machine's own Z (no mesh, no tag offset): home is Z8">Clear at</label>
    <div class="note" title="It moves sideways only this high or higher, clear of everything raised on the bed (clear_z in pens.toml); it goes down only over the spot it shoots">Z ${num(c.clear_z, 2)} · lowest Z ${num(lo, 2)}</div>
    ${fld('z', 'Focus z', num(s.z, 2), `step="0.05" min="${lo}" max="${hi}" placeholder="${num(c.focus_z, 2)}"`,
      `Machine Z of the camera when shooting: where it is sharpest. Empty: the camera's own (${num(c.focus_z, 2)}). Find it with Focus (K) on the bed. From ${lo} (its z_min) to ${hi}`)}
    ${fld('overlap', 'Overlap %', num(s.overlap * 100, 0), 'step="5" min="0" max="80"', 'How much of a shot the next one shares: more for stitching, less for fewer shots')}
    ${fld('refocus', 'Refocus ±', num(s.refocus, 2), 'step="0.05" min="0"', 'mm up and down around the focus z at every tile, keeping the sharpest shot: for film or paper that curls. 0: off (quicker)')}
    ${fld('refocus_step', 'its step', num(s.refocus_step, 2), 'step="0.05" min="0.05"', 'Steps of that refocus sweep, mm')}
    ${fld('settle', 'Settle s', num(s.settle, 2), `step="0.1" min="0" placeholder="${num(c.settle, 1)}"`, `Seconds still before each shot (the tether swinging, frames the camera has queued). Empty: the camera's own (${c.settle})`)}
    <label title="The focus sweep, machine Z: from, to, step. It goes down from the top, never under the camera's lowest Z">Sweep</label>
    <div class="row region" title="The focus sweep: from, to, step (machine Z)">
      <input data-s="w0" type="number" step="0.25" min="${lo}" value="${num(sw[0], 2)}" title="Focus sweep: its lowest z (not under ${lo})">
      <input data-s="w1" type="number" step="0.25" max="${hi}" value="${num(sw[1], 2)}" title="Focus sweep: its highest z (it starts there)">
      <input data-s="w2" type="number" step="0.05" min="0.05" value="${num(sw[2], 2)}" title="Focus sweep: step">
    </div>
    <label></label><label class="check" title="Stay at the shooting z between tiles instead of lifting to the clear height: quicker, only for a flat region with nothing raised in it"><input type="checkbox" data-s="low"${s.low ? ' checked' : ''}> stay low between tiles</label>
    <label></label><div class="note">${n ? `${n} shot${n > 1 ? 's' : ''}, about ${Math.ceil(n * per / 60)} min` : 'Draw a region on the bed (R)'}</div>`);
}
$('#camera').addEventListener('change', async (e) => {
  const t = e.target, k = t.dataset.s;
  if (!k) return;
  const s = C.settings, v = t.value === '' ? null : +t.value;
  if (k === 'tool') return patchScan({ tool: t.value });
  if (k[0] === 'r' && k.length === 2) {
    const r = [...(s.region || [0, 0, 0, 0])];
    r[+k[1]] = v ?? 0;
    return patchScan({ region: r });
  }
  if (k === 'low') return patchScan({ low: t.checked });
  if (k[0] === 'w' && k.length === 2) {
    const w = [...sweepOf(cam())];
    w[+k[1]] = v ?? w[+k[1]];
    return patchScan({ sweep: w });
  }
  if (k === 'overlap') return patchScan({ overlap: (v ?? 20) / 100 });
  patchScan({ [k]: v ?? (k === 'refocus' ? 0 : k === 'refocus_step' ? 0.1 : null) });
});
$('#camera').addEventListener('click', async (e) => {
  if (e.target.dataset.act !== 'write-cam') return;
  const holder = $('#c-holder').value, pen = $('#c-type').value, name = $('#c-name').value.trim();
  if (!confirm(`Dock holder ${holder}'s tool, write ${pen} "${name}" onto its tag, and put it back?`)) return;
  const r = await api('POST', `/api/holders/${holder}/tag`, { pen, name });
  printer = { ...(printer || {}), job: r.job };
  toast('Writing the tag…');
  watchJob();
});

// --- jobs --------------------------------------------------------------------------
function renderJob() {
  const P = $('#camera-job');
  if (!C) return;
  const j = C.job, busy = j && !j.done, has = Object.keys(C.cameras).length;
  const pct = j && j.n ? Math.round(100 * j.i / j.n) : 0;
  let status = '<span class="note">Nothing running.</span>';
  if (j) {
    status = busy ? `<b>${esc(j.what)}…</b> ${j.n ? `${j.i} / ${j.n}` : ''}<div class="bar" title="${pct}%"><i style="width:${pct}%"></i></div>`
      : j.error ? `<span class="bad" title="${esc(j.error)}">⚠ ${esc(j.what)}: ${esc(j.error)}</span>` : `${esc(j.what)}: done`;
  }
  let focus = '';
  if (j && j.result && j.result.curve) {
    const cv = j.result.curve, zs = cv.map((p) => p[0]), sc = cv.map((p) => p[1]);
    const z0 = Math.min(...zs), z1 = Math.max(...zs), s1 = Math.max(...sc) || 1;
    const pts = cv.map(([z, v]) => `${(z - z0) / ((z1 - z0) || 1) * 200},${60 - v / s1 * 56}`).join(' ');
    const bx = (j.result.z - z0) / ((z1 - z0) || 1) * 200;
    focus = `<div class="curve" title="Sharpness against z: the peak is the focus">
      <svg viewBox="-4 0 208 62"><polyline points="${pts}"/><line x1="${bx}" x2="${bx}" y1="0" y2="62"/></svg>
      <div class="row"><span class="note">sharpest at z ${num(j.result.z, 2)}</span>
      <button data-act="use-z" data-z="${j.result.z}" title="Shoot at this z from now on">Use it</button></div></div>`;
  }
  const last = j && j.scan ? `<img class="last" data-open="${esc(j.scan)}" src="/api/captures/${encodeURIComponent(j.scan)}/thumb/${
    j.what === 'finding the focus' ? 'best.jpg' : j.what === 'looking' ? 'look.jpg' : 'latest'}?t=${j.i}" alt="" title="The last shot: click to open" onerror="this.remove()">` : '';
  fill(P, `
    <div class="buttons wrap">
      <button data-act="look" ${busy || !has || !C.settings.region ? 'disabled' : ''} title="One shot at the middle of the region, at the focus z (or click the bed with Look, L)">Look</button>
      <button data-act="focus" ${busy || !has || !C.settings.region ? 'disabled' : ''} title="Sweep z at the middle of the region and find where it is sharpest (or click the bed with Focus, K)">Find focus</button>
      <button data-act="scan" class="primary" ${busy || !has || !C.settings.region ? 'disabled' : ''} title="Take every tile of the region: it picks up the camera first if it isn't on the carriage">Scan region</button>
      <button data-act="stop" ${busy ? '' : 'disabled'} title="Stop after the shot it is taking">Stop</button>
      <button data-act="park" ${busy || !has ? 'disabled' : ''} title="Put the camera back in its holder">Put away</button>
    </div>
    <div class="job">${status}</div>${focus}${last}`);
}
$('#camera-job').addEventListener('click', async (e) => {
  const t = e.target, act = t.dataset.act;
  if (t.dataset.open) return openCapture(t.dataset.open);
  if (!act) return;
  const r = C.settings.region, mid = r ? { x: (r[0] + r[2]) / 2, y: (r[1] + r[3]) / 2 } : null;
  if (act === 'use-z') return patchScan({ z: +t.dataset.z });
  if (act === 'stop') { await api('POST', '/api/camera/stop'); return loadCamera(); }
  if (act === 'park') {
    if (!confirm('Put the camera back in its holder?')) return;
    const res = await api('POST', '/api/camera/park');
    printer = { ...(printer || {}), job: res.job };
    toast('Putting the camera away…');
    return watchJob();
  }
  if (act === 'look') await api('POST', '/api/camera/look', { ...mid, z: focusZ() });
  if (act === 'focus') await api('POST', '/api/camera/focus', mid);
  if (act === 'scan') {
    const n = scanTiles().length;
    if (!confirm(`Scan the region: ${n} shot${n > 1 ? 's' : ''} at z ${num(focusZ(), 2)}?`)) return;
    await api('POST', '/api/camera/scan');
  }
  loadCamera();
});

// --- captures: the list and the viewer ---------------------------------------------------
const when = (id) => id.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2}).*/, '$3.$2. $4:$5');
const kinds = { scan: '▦', focus: '◎', look: '◉' };
function renderCaptures() {
  if (!C) return;
  fill($('#captures'), C.captures.map((c) => `
    <li data-id="${esc(c.id)}" class="${viewing && viewing.meta.id === c.id ? 'on' : ''}" title="${esc(c.kind)} ${esc(c.id)}: ${c.count} shot${c.count === 1 ? '' : 's'}${c.region ? ` over ${c.region.map((v) => num(v, 1)).join(', ')}` : ''}${c.error ? ` (${c.error})` : ''}">
      <span class="kind">${kinds[c.kind] || '·'}</span>
      <span class="name">${esc(when(c.id))} <span class="note">${esc(c.kind)} · ${c.count}${c.done ? '' : ' …'}</span></span>
      <a class="icon" href="/api/captures/${encodeURIComponent(c.id)}/zip" title="Download all its shots (zip)">⤓</a>
      <button class="icon" data-del="${esc(c.id)}" title="Delete it from the server">✕</button>
    </li>`).join('') || '<li class="note">Nothing yet: look, focus or scan with the camera tool.</li>');
}
$('#captures').addEventListener('click', async (e) => {
  const del = e.target.dataset.del;
  if (del) {
    if (!confirm(`Delete ${del} from the server?`)) return;
    await api('DELETE', `/api/captures/${encodeURIComponent(del)}`);
    if (viewing && viewing.meta.id === del) closeViewer();
    return loadCamera();
  }
  if (e.target.closest('a')) return;
  const li = e.target.closest('li[data-id]');
  if (li) openCapture(li.dataset.id);
});

// Each capture's meta.json and, for a scan, where its tiles really are (registered)
const known = {};               // id -> {count, meta, info}
async function capture(id, count) {
  const k = known[id];
  if (k && k.count === count) return k;
  const meta = await api('GET', `/api/captures/${encodeURIComponent(id)}`);
  let info = null;
  if (meta.kind === 'scan' && meta.tiles.length) {
    try { info = await api('GET', `/api/captures/${encodeURIComponent(id)}/stitch/info`); } catch { /* nothing yet */ }
  }
  return (known[id] = { count, meta, info });
}
const PPMS = [12, 25, 50, 80];

async function openCapture(id, view) {
  const c = (C.captures || []).find((x) => x.id === id);
  const k = await capture(id, c ? c.count : -1);
  viewing = { meta: k.meta, info: k.info, view: view || (k.meta.kind === 'scan' && k.meta.tiles.length > 1 ? 'stitch' : 'tiles'),
              ppm: store.get('stitchPpm', 25) };
  renderViewer(); renderCaptures(); drawScanLayer();
}
function closeViewer() {
  viewing = null;
  $('#viewer').hidden = true;
  if (C) renderCaptures();
  drawScanLayer();
}
async function renderViewer() {
  const V = $('#viewer'), m = viewing && viewing.meta;
  if (!m) { V.hidden = true; return; }
  V.hidden = false;
  const id = encodeURIComponent(m.id), view = viewing.view;
  const tiles = m.tiles || [];
  const pinned = store.get('scanUnder', null) === m.id;
  let body;
  if (view === 'stitch') {
    const ppm = viewing.ppm, native = (viewing.info && viewing.info.native_ppm) || 126;
    const opts = [...PPMS, Math.round(native)].map((v) => `<option value="${v}"${v === ppm ? ' selected' : ''}>${v === Math.round(native) ? `${v} px/mm (full)` : `${v} px/mm`}</option>`).join('');
    let size = '';
    try {
      const inf = await api('GET', `/api/captures/${id}/stitch/info?px_per_mm=${ppm}`);
      size = `${inf.width} × ${inf.height} px, ${inf.mp} MP · ${inf.used} of ${inf.of} overlaps matched, tiles moved up to ${num(inf.moved_max, 2)} mm`
        + (inf.too_big ? ' · too big: pick a lower px/mm' : '');
    } catch { size = 'no tiles yet'; }
    body = `<div class="row stitchbar">
        <select id="v-ppm" title="Resolution of the stitch: the camera takes ~${Math.round(native)} px/mm; higher is bigger and slower">${opts}</select>
        <span class="note">${esc(size)}</span>
        <a class="button" href="/api/captures/${id}/stitch?px_per_mm=${ppm}&download=1" title="Download the stitch at this resolution (JPEG)">⤓ stitched</a></div>
      <div class="stitching note" id="v-wait">stitching…</div>
      <img class="big" src="/api/captures/${id}/stitch?px_per_mm=${ppm}&t=${tiles.length}" alt="stitched"
        onload="document.getElementById('v-wait').remove()" onerror="document.getElementById('v-wait').textContent='could not stitch it'"
        title="The tiles joined where their overlaps agree (registered), the seams faded">`;
  } else if (view === 'tiles') {
    body = `<div class="grid-tiles">${tiles.map((t) => `<img data-file="${esc(t.file)}" loading="lazy" src="/api/captures/${id}/thumb/${encodeURIComponent(t.file)}"
      title="${esc(t.file)}: X ${num(t.x, 2)} Y ${num(t.y, 2)} z ${num(t.z, 2)}. Click for the full photo">`).join('')}</div>`;
  } else {
    const i = tiles.findIndex((t) => t.file === view), t = tiles[i] || {};
    body = `<a href="/api/captures/${id}/file/${encodeURIComponent(view)}" target="_blank" title="Open the full photo in a new tab">
      <img class="big" src="/api/captures/${id}/file/${encodeURIComponent(view)}" alt="${esc(view)}"></a>
      <div class="note mono">${esc(view)} · X ${num(t.x, 2)} Y ${num(t.y, 2)} z ${num(t.z, 2)} · ${i + 1} / ${tiles.length} (← →)</div>`;
  }
  fill(V, `<div class="vbar">
      <b title="${esc(m.kind)} taken ${esc(m.id)}">${esc(when(m.id))} · ${esc(m.kind)}</b>
      <div class="seg small">
        ${m.kind === 'scan' ? `<button data-view="stitch" class="${view === 'stitch' ? 'on' : ''}" title="All tiles as one picture: registered on their overlaps, seams faded">Stitched</button>` : ''}
        <button data-view="tiles" class="${view === 'tiles' || view.endsWith('.jpg') ? 'on' : ''}" title="Every shot on its own">Tiles</button>
      </div>
      ${m.kind === 'scan' ? `<button data-act="pin" class="${pinned ? 'primary' : ''}" title="Show this scan under the drawings on the Plot tab, where it was taken: place a plot on what is on the bed">${pinned ? '✓ under the plot' : 'Under the plot'}</button>` : ''}
      <span class="grow"></span>
      <a class="button" href="/api/captures/${id}/zip" title="Download all its shots (zip)">⤓ zip</a>
      <button data-act="close" title="Close (Esc)">✕</button>
    </div><div class="vbody">${body}</div>`);
}
$('#viewer').addEventListener('click', (e) => {
  const t = e.target;
  if (t.dataset.view) { viewing.view = t.dataset.view; return renderViewer(); }
  if (t.dataset.file) { viewing.view = t.dataset.file; return renderViewer(); }
  if (t.dataset.act === 'close') return closeViewer();
  if (t.dataset.act === 'pin') {
    const pinned = store.get('scanUnder', null) === viewing.meta.id;
    store.set('scanUnder', pinned ? null : viewing.meta.id);
    toast(pinned ? 'No scan under the plot' : 'Pinned: on the Plot tab it lies under the drawings');
    renderViewer(); drawUnder();
  }
});
$('#viewer').addEventListener('change', (e) => {
  if (e.target.id === 'v-ppm') { viewing.ppm = +e.target.value; store.set('stitchPpm', viewing.ppm); renderViewer(); }
});
function stepTile(d) {
  const tiles = viewing.meta.tiles, i = tiles.findIndex((t) => t.file === viewing.view);
  if (i < 0) return false;
  viewing.view = tiles[(i + d + tiles.length) % tiles.length].file;
  renderViewer();
  return true;
}

// --- the bed: shots where they were taken, the region, its tiles ----------------------------
function shotImage(L, id, k, extra = {}) {
  // A scan: its stitch where its tiles really are. A look or a focus: the shot, turned upright
  const m = k.meta;
  if (m.kind === 'scan' && k.info) {
    const [x0, y0, x1, y1] = k.info.extent;
    return svgEl('image', { href: `/api/captures/${encodeURIComponent(id)}/stitch?px_per_mm=${extra.ppm || 12}&t=${m.tiles.length}`,
      x: x0, y: -y1, width: x1 - x0, height: y1 - y0, transform: 'scale(1,-1)', preserveAspectRatio: 'none', ...extra.attrs }, L);
  }
  const t = m.tiles[m.tiles.length - 1];
  if (!t) return null;
  const [w, h] = m.fov, turn = m.turn || 0;
  return svgEl('image', { href: `/api/captures/${encodeURIComponent(id)}/thumb/${encodeURIComponent(t.file)}`, x: -w / 2, y: -h / 2,
    width: w, height: h, preserveAspectRatio: 'none', transform: `translate(${t.x} ${t.y}) scale(1,-1) rotate(${-turn})`, ...extra.attrs }, L);
}
let layerPending = false;
function drawScanLayer() {
  const L = $('#scan-layer');
  L.innerHTML = '';
  if (!scanTab() || !C) return;
  if ($('#shots-on-bed').checked) {
    const shown = C.captures.filter((c) => c.count).slice(0, 12).reverse();
    for (const c of shown) {
      const k = known[c.id];
      if (!k || k.count !== c.count) {
        if (!layerPending) {
          layerPending = true;
          Promise.all(shown.map((x) => capture(x.id, x.count).catch(() => null))).finally(() => { layerPending = false; drawScanLayer(); });
        }
        continue;
      }
      const img = shotImage(L, c.id, k, { attrs: { class: 'shot' + (viewing && viewing.meta.id === c.id ? ' on' : '') } });
      if (img) svgEl('title', {}, img).textContent = `${c.kind} ${c.id}`;
    }
  }
  const r = sdrag ? [Math.min(sdrag.a.x, sdrag.b.x), Math.min(sdrag.a.y, sdrag.b.y), Math.max(sdrag.a.x, sdrag.b.x), Math.max(sdrag.a.y, sdrag.b.y)]
    : C.settings.region;
  if (r) {
    const c = cam();
    if (c && !sdrag) {
      const [fx, fy] = footprint(c.fov, c.turn || 0);
      scanTiles().forEach(([x, y], i) => {
        const t = svgEl('rect', { class: 'scan-tile', x: x - fx / 2, y: y - fy / 2, width: fx, height: fy }, L);
        svgEl('title', {}, t).textContent = `shot ${i + 1} at X ${num(x, 1)} Y ${num(y, 1)}`;
      });
    }
    const box = svgEl('rect', { class: 'scan-region', x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1] }, L);
    svgEl('title', {}, box).textContent = `Region ${r.map((v) => num(v, 1)).join(', ')}`;
  }
}
$('#shots-on-bed').addEventListener('change', drawScanLayer);

// The scan pinned under the plot (Plot tab): drawings are placed on what is on the bed
async function drawUnder() {
  const L = $('#scan-under'), id = store.get('scanUnder', null);
  $('#under-toggle').hidden = !id;
  L.innerHTML = '';
  if (!id || !$('#show-under').checked) return;
  let k;
  try {
    const list = (C && C.captures) || await api('GET', '/api/captures');
    const c = list.find((x) => x.id === id);
    if (!c) { store.set('scanUnder', null); $('#under-toggle').hidden = true; return; }
    k = await capture(id, c.count);
  } catch { return; }
  const img = shotImage(L, id, k, { ppm: 25, attrs: { class: 'under' } });
  if (img) svgEl('title', {}, img).textContent = `The scan ${id}, where it was taken`;
}
$('#show-under').addEventListener('change', drawUnder);

// Region, look and focus on the canvas; pan goes on to app.js
svg.addEventListener('pointerdown', async (e) => {
  if (!scanTab() || e.button !== 0 || spaceDown || smode === 'pan') return;
  e.stopImmediatePropagation();
  e.preventDefault();
  const p = worldPt(e);
  if (smode === 'region') {
    sdrag = { a: p, b: p };
    try { svg.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ }
    return drawScanLayer();
  }
  if (!Object.keys(C.cameras).length) return toast('No camera tool: write its tag first (Camera panel)', true);
  const x = +p.x.toFixed(2), y = +p.y.toFixed(2);
  if (smode === 'look') {
    await api('POST', '/api/camera/look', { x, y, z: focusZ() });
    toast(`Looking at X ${num(x, 1)} Y ${num(y, 1)}…`);
  } else {
    await api('POST', '/api/camera/focus', { x, y });
    toast(`Finding the focus at X ${num(x, 1)} Y ${num(y, 1)}…`);
  }
  loadCamera();
}, true);
svg.addEventListener('pointermove', (e) => {
  if (!sdrag) return;
  sdrag.b = worldPt(e);
  drawScanLayer();
  hint(`${num(Math.abs(sdrag.b.x - sdrag.a.x), 1)} × ${num(Math.abs(sdrag.b.y - sdrag.a.y), 1)} mm`);
});
svg.addEventListener('pointerup', async () => {
  const d = sdrag;
  if (!d) return;
  sdrag = null;
  hint('');
  const snap = (v) => Math.round(v * 2) / 2;
  const r = [snap(Math.min(d.a.x, d.b.x)), snap(Math.min(d.a.y, d.b.y)), snap(Math.max(d.a.x, d.b.x)), snap(Math.max(d.a.y, d.b.y))];
  if (r[2] - r[0] < 1 || r[3] - r[1] < 1) return drawScanLayer();
  await patchScan({ region: r });
});

function setSmode(m) {
  smode = m;
  $$('#scan-rail [data-smode]').forEach((b) => b.classList.toggle('on', b.dataset.smode === m));
  svg.classList.toggle('pan-mode', m === 'pan');
  svg.classList.toggle('scan-pick', m !== 'pan');
}
$('#scan-rail').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.smode) setSmode(b.dataset.smode);
  if (b.dataset.sact === 'fit') fit();
});

// Keys on the Scan tab (app.js asks first): true when taken
window.scanKey = (e) => {
  if (e.ctrlKey || e.metaKey) return false;
  const key = e.key.toLowerCase();
  if (e.key === 'Escape') { if (viewing) closeViewer(); else setSmode('region'); return true; }
  if (viewing && typeof viewing.view === 'string' && viewing.view.endsWith('.jpg') && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
    return stepTile(e.key === 'ArrowLeft' ? -1 : 1);
  }
  const modes = { r: 'region', h: 'pan', l: 'look', k: 'focus' };
  if (modes[key]) { setSmode(modes[key]); return true; }
  if (key === 'f') { fit(); return true; }
  return ['v', 'p', 'd', 'delete', 'backspace', 'arrowleft', 'arrowright', 'arrowup', 'arrowdown'].includes(key);
};

setSmode('region');
document.body.classList.toggle('tab-scan', store.get('tab', 'plot') === 'scan');
document.body.classList.toggle('tab-plot', store.get('tab', 'plot') !== 'scan');
(function whenLoaded() {                // app.js loads the state first
  if (S) setTab(store.get('tab', 'plot'));
  else setTimeout(whenLoaded, 100);
})();
