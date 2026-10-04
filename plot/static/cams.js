// Limn plot - Klipper's cameras, live, in an overlay; and the links to Fluidd.
// /api/webcams has Moonraker's list and where Fluidd is ('' : this page's host).
// Their URLs are mostly relative to Fluidd: taken from there, not from this page.
// When Moonraker is on the plot server's own host, where Fluidd is for the browser
// can only be guessed (this page's host): the Printer panel sets it (settings.json).
// A stream is only open while it is shown: the Pi serves every viewer.
'use strict';

let W = null;                   // /api/webcams
const camStore = { get: (d) => store.get('webcam', d), set: (v) => store.set('webcam', v) };

function fluiddBase() {
  return (W && W.fluidd) || `${location.protocol}//${location.hostname}`;
}
function camUrl(u) {
  if (!u) return '';
  return /^https?:\/\//.test(u) ? u : fluiddBase().replace(/\/$/, '') + (u.startsWith('/') ? u : '/' + u);
}
async function loadWebcams() {
  try { W = await api('GET', '/api/webcams'); } catch { W = { fluidd: '', webcams: [], error: 'no answer' }; }
  try { W.settings = await api('GET', '/api/settings'); } catch { W.settings = {}; }
  $('#fluidd-link').href = fluiddBase();
  renderPrinterUrl();
  return W;
}
function renderPrinterUrl() {
  const el = $('#printer-url');
  if (!el || !W) return;
  fill(el, `<label for="printer-url-in">Fluidd at</label>
    <div class="row nowrap"><input id="printer-url-in" type="url" inputmode="url" placeholder="${esc(fluiddBase())}" value="${esc(W.set ? W.fluidd : '')}"
      title="Where Fluidd is, as this browser gets to it: the cameras' addresses are taken from it. Empty: ${esc(W.guessed ? 'this page\'s host' : 'the profile, or Moonraker\'s host')}">
      <button data-act="save-url">Set</button></div>
    <p class="note">${W.set ? 'Set here; empty it to go back to the default.' : W.guessed
      ? 'Guessed from this page’s address: if the cameras don’t show, give Fluidd’s (eg. https://limn.local).' : 'From the profile, or Moonraker’s host.'}</p>
    <label for="endoscope-url-in">Endoscope at</label>
    <div class="row nowrap"><input id="endoscope-url-in" type="url" inputmode="url" placeholder="http://laptop:4240/snapshot.jpg?flip=1" value="${esc((W.settings || {}).endoscope_url || '')}"
      title="The endoscope's snapshot URL (limn_endoscope's web server, as the plot server reaches it): it becomes a camera on the Scan tab, fixed on the carriage (no holder, Z never moved). Empty: none">
      <button data-act="save-endoscope">Set</button></div>`);
}
async function savePrinterUrl() {
  const v = $('#printer-url-in').value.trim();
  await api('PUT', '/api/settings', { printer_url: v });
  await loadWebcams();
  toast(v ? `Fluidd and its cameras at ${v}` : 'Fluidd: back to the default');
  if (!$('#cams').hidden) showCams();
}
async function saveEndoscopeUrl() {
  const v = $('#endoscope-url-in').value.trim();
  try { await api('PUT', '/api/settings', { endoscope_url: v }); } catch (e) { return toast(String(e.message || e), true); }
  await loadWebcams();
  if (typeof loadCamera === 'function') loadCamera();
  toast(v ? `Endoscope: ${v}` : 'No endoscope');
}
$('#printer-url').addEventListener('click', (e) => {
  if (e.target.dataset.act === 'save-url') savePrinterUrl();
  if (e.target.dataset.act === 'save-endoscope') saveEndoscopeUrl();
});
$('#printer-url').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.id === 'printer-url-in') savePrinterUrl();
  if (e.key === 'Enter' && e.target.id === 'endoscope-url-in') saveEndoscopeUrl();
});

async function showCams(name) {
  const P = $('#cams');
  if (!W) await loadWebcams();
  const cams = W.webcams;
  if (!cams.length) {
    P.hidden = false;
    fill(P, `<div class="vbar"><b>Cameras</b><span class="grow"></span><button data-act="cams-close" title="Close">✕</button></div>
      <p class="note">${esc(W.error || 'Klipper has no cameras.')}</p>`);
    return;
  }
  const scanCam = document.body.classList.contains('tab-scan') && typeof cam === 'function' && cam() && cam().webcam;
  const cur = cams.find((c) => c.name === (name || camStore.get(scanCam || ''))) || cams.find((c) => c.name === scanCam) || cams[0];
  camStore.set(cur.name);
  const t = [`rotate(${cur.rotation || 0}deg)`, cur.flip_horizontal ? 'scaleX(-1)' : '', cur.flip_vertical ? 'scaleY(-1)' : ''].join(' ');
  const live = cur.service !== 'iframe' && cur.stream_url;
  P.hidden = false;
  fill(P, `<div class="vbar">
      <div class="seg small">${cams.map((c) => `<button data-cam="${esc(c.name)}" class="${c === cur ? 'on' : ''}" title="${esc(c.service || '')}">${esc(c.name)}</button>`).join('')}</div>
      <span class="grow"></span>
      <a class="button" href="${esc(camUrl(cur.snapshot_url))}" target="_blank" title="One still picture, in a new tab">snapshot ↗</a>
      <a class="button" href="${esc(camUrl(cur.stream_url))}" target="_blank" title="The stream on its own, in a new tab">open ↗</a>
      <button data-act="cams-close" title="Close (the stream stops)">✕</button>
    </div>
    <div class="vbody">${live ? `<img class="live" src="${esc(camUrl(cur.stream_url))}" alt="${esc(cur.name)}" style="transform:${t}"
      onerror="this.replaceWith(Object.assign(document.createElement('p'), {className: 'note', textContent: 'The stream doesn\\'t answer at ' + this.src + '. Where Fluidd is: the Printer panel.'}))">`
      : `<iframe src="${esc(camUrl(cur.stream_url))}" title="${esc(cur.name)}"></iframe>`}</div>`);
}
function hideCams() {
  const P = $('#cams');
  P.hidden = true;
  P.innerHTML = '';                 // drops the stream's connection
}
$('#cams').addEventListener('click', (e) => {
  const t = e.target.closest('button');
  if (!t) return;
  if (t.dataset.cam) showCams(t.dataset.cam);
  if (t.dataset.act === 'cams-close') hideCams();
});
$('#cams-button').addEventListener('click', () => ($('#cams').hidden ? showCams() : hideCams()));
loadWebcams();
