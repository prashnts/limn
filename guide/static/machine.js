// The machine page's picture: what is under the pointer lit and named. img/machine-ids.png is the
// same view with every mesh a flat colour that is its number (16 levels a channel, render/shot.py);
// machine-map.json gives each number its pages, from the machine's big assemblies down to the
// single design. The level buttons pick how deep a hover goes; the list beside it lights the same.
const box = document.querySelector('.mmap');
const LIT = [226, 113, 29];

if (box) start().catch(e => console.warn('machine map:', e));

async function start() {
  const base = box.querySelector('.mm-base'), hl = box.querySelector('.mm-hl'), tip = box.querySelector('.mm-tip');
  const root = box.dataset.root;
  const [map, ids, shot] = await Promise.all([
    fetch(box.dataset.map).then(r => r.json()), pixels(box.dataset.ids), pixels(base.src)]);
  const { width: W, height: H } = hl;
  const n = W * H;
  const id = new Uint16Array(n);                     // each pixel: its mesh's number, 0 the background
  for (let i = 0, p = 0; i < n; i++, p += 4) {
    const r = Math.round(ids[p] / 17), g = Math.round(ids[p + 1] / 17), b = Math.round(ids[p + 2] / 17);
    id[i] = (r << 8) | (g << 4) | b;
  }
  const meshes = map.meshes, pages = map.pages;
  let level = 1, cur = null, pinned = false;
  const pageOf = new Array(4096).fill(null);         // mesh -> the page a hover names, at this level
  const relevel = () => {
    pageOf.fill(null);
    for (const [m, { chain }] of Object.entries(meshes))
      pageOf[m] = level === 0 ? chain[chain.length - 1] : chain[Math.min(level, chain.length) - 1];
  };
  relevel();
  const ctx = hl.getContext('2d');

  // Light every pixel whose mesh `has` says; nothing (or a speck) seen: a ring where it is
  function light(slug, has) {
    const out = ctx.createImageData(W, H), d = out.data;
    const lut = new Uint8Array(4096);
    for (const m in meshes) if (has(+m)) lut[m] = 1;
    let count = 0;
    for (let i = 0, p = 0; i < n; i++, p += 4) {
      if (!lut[id[i]]) continue;
      count++;
      d[p] = shot[p] * 0.55 + LIT[0] * 0.45; d[p + 1] = shot[p + 1] * 0.55 + LIT[1] * 0.45;
      d[p + 2] = shot[p + 2] * 0.55 + LIT[2] * 0.45; d[p + 3] = 255;
    }
    ctx.putImageData(out, 0, 0);
    if (count < 150) {                                // inside the machine: where it is
      ctx.strokeStyle = `rgb(${LIT})`; ctx.lineWidth = 4;
      for (const m in meshes) {
        if (!lut[m]) continue;
        const [x0, y0, x1, y1] = meshes[m].box;
        const cx = (x0 + x1) / 2 * W, cy = (y0 + y1) / 2 * H, r = Math.max(14, (x1 - x0) * W / 2 + 6);
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.stroke();
      }
    }
    box.classList.add('lit');
    cur = slug;
  }
  function clear() {
    ctx.clearRect(0, 0, W, H);
    box.classList.remove('lit');
    tip.hidden = true;
    cur = null;
  }
  function name(slug, x, y) {
    const p = pages[slug];
    const trail = (Object.values(meshes).find(m => m.chain.includes(slug)) || { chain: [] }).chain;
    const up = trail.slice(0, trail.indexOf(slug)).map(s => pages[s]?.name).filter(Boolean);
    tip.href = `${root}parts/${slug}.html`;
    tip.innerHTML = `${p.thumb ? `<img src="${root}${p.thumb}" alt="">` : ''}<span><b>${esc(p.name)}</b>`
      + `<small>${esc(p.kind)}${p.qty > 1 ? ` · ×${p.qty} in Limn` : ''}</small>`
      + (up.length ? `<small class="up">${up.map(esc).join(' › ')}</small>` : '') + '</span>';
    tip.hidden = false;
    const r = box.getBoundingClientRect();
    tip.style.left = `${Math.min(x, r.width - tip.offsetWidth - 4)}px`;
    tip.style.top = `${y + 18 + tip.offsetHeight > r.height ? y - tip.offsetHeight - 12 : y + 18}px`;
  }
  const at = e => {                                   // the page under a pointer event, and where
    const r = box.getBoundingClientRect();
    const x = Math.floor((e.clientX - r.left) / r.width * W), y = Math.floor((e.clientY - r.top) / r.height * H);
    if (x < 0 || y < 0 || x >= W || y >= H) return [null];
    return [pageOf[id[y * W + x]], e.clientX - r.left, e.clientY - r.top];
  };
  box.addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse' || pinned) return;
    const [slug, x, y] = at(e);
    if (!slug) return clear();
    if (slug !== cur) light(slug, m => pageOf[m] === slug);
    name(slug, x, y);
  });
  box.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && !pinned) clear(); });
  box.addEventListener('click', e => {
    if (e.target.closest('.mm-tip')) return;          // its link
    const [slug, x, y] = at(e);
    if (!slug) { pinned = false; return clear(); }
    if (e.pointerType === 'mouse' || (e.pointerType === undefined && matchMedia('(hover: hover)').matches)) {
      location.href = `${root}parts/${slug}.html`;
      return;
    }
    pinned = true;                                    // touch: name it, its name opens it
    light(slug, m => pageOf[m] === slug);
    name(slug, x, y);
  });
  for (const b of document.querySelectorAll('.mm-levels button')) {
    b.addEventListener('click', () => {
      level = +b.dataset.level;
      document.querySelectorAll('.mm-levels button').forEach(x => x.classList.toggle('on', x === b));
      relevel(); clear();
    });
  }
  // The list: a design pointed at there is lit here, every copy of it, at any level
  for (const a of document.querySelectorAll('.mtree a.tnode')) {
    const slug = a.getAttribute('href').split('/').pop().replace('.html', '');
    if (!pages[slug]) continue;
    a.addEventListener('mouseenter', () => { pinned = false; tip.hidden = true; light(slug, m => meshes[m].chain.includes(slug)); });
    a.addEventListener('mouseleave', clear);
  }
}

function pixels(src) {
  return new Promise((ok, bad) => {
    const im = new Image();
    im.onload = () => {
      const c = document.createElement('canvas');
      c.width = im.naturalWidth; c.height = im.naturalHeight;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(im, 0, 0);
      ok(g.getImageData(0, 0, c.width, c.height).data);
    };
    im.onerror = bad;
    im.src = src;
  });
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
