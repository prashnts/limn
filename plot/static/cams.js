// Limn plot - Klipper's cameras, live, in an overlay; and the links to Fluidd.
// /api/webcams has Moonraker's list and where Fluidd is ('' : this page's host).
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
  $('#fluidd-link').href = fluiddBase();
  return W;
}

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
      onerror="this.replaceWith(Object.assign(document.createElement('p'), {className: 'note', textContent: 'The stream doesn\\'t answer.'}))">`
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
