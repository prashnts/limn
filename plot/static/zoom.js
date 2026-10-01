// Limn plot - zooming a picture in its box: the scan viewer's stitches, tiles and corners.
// Wheel or pinch zooms at the pointer, a drag or two fingers on a trackpad pan, a
// double-click goes from fitted to full size (a pixel of the photo a pixel of the
// screen) and back. A click that didn't drag still goes through (the corners take it).
// zoomable(box): box is a .zoombox, its first child what zooms (filling the box).
'use strict';

function zoomable(box) {
  if (box.dataset.zoomable) return;
  box.dataset.zoomable = '1';
  const inner = box.firstElementChild;
  let k = 1, x = 0, y = 0, drag = null, dragged = false, pinch = 1;
  const badge = document.createElement('span');
  badge.className = 'zoombadge';
  box.append(badge);
  inner.style.transformOrigin = '0 0';
  function apply() {
    const W = box.clientWidth, H = box.clientHeight;
    k = Math.min(Math.max(k, 1), 60);
    x = Math.min(0, Math.max(W - W * k, x));          // the picture always fills the box
    y = Math.min(0, Math.max(H - H * k, y));
    inner.style.transform = k === 1 ? '' : `translate(${x}px, ${y}px) scale(${k})`;
    badge.textContent = k === 1 ? '' : `${Math.round(k * 100)} %`;
    box.classList.toggle('zoomed', k > 1);
  }
  function zoomAt(f, e) {
    const r = box.getBoundingClientRect(), cx = e.clientX - r.left, cy = e.clientY - r.top;
    const nk = Math.min(Math.max(k * f, 1), 60);
    x = cx - (cx - x) * (nk / k);
    y = cy - (cy - y) * (nk / k);
    k = nk;
    apply();
  }
  box.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (e.ctrlKey) return zoomAt(Math.exp(-e.deltaY * 0.01), e);                  // a pinch
    if (typeof isWheel !== 'function' || isWheel(e)) return zoomAt(Math.exp(-e.deltaY * 0.0015), e);
    x -= e.deltaX; y -= e.deltaY;                                                 // two fingers
    apply();
  }, { passive: false });
  box.addEventListener('gesturestart', (e) => { e.preventDefault(); pinch = 1; });
  box.addEventListener('gesturechange', (e) => { e.preventDefault(); zoomAt(e.scale / pinch, e); pinch = e.scale; });
  box.addEventListener('pointerdown', (e) => {
    if (k === 1 && e.button === 0) return;              // nothing to pan: a click stays a click
    drag = { sx: e.clientX, sy: e.clientY, x, y, id: e.pointerId };
    dragged = false;
  });
  box.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!dragged && Math.abs(dx) + Math.abs(dy) > 3) {
      dragged = true;                                   // a drag, not a click: the box has the pointer now
      try { box.setPointerCapture(drag.id); } catch { /* not a real pointer */ }
    }
    if (!dragged) return;
    x = drag.x + dx; y = drag.y + dy;
    apply();
  });
  box.addEventListener('pointerup', () => { drag = null; });
  box.addEventListener('click', (e) => {                // after a drag: not a click
    if (dragged) { e.stopPropagation(); e.preventDefault(); dragged = false; }
  }, true);
  box.addEventListener('contextmenu', (e) => e.preventDefault());
  box.addEventListener('dblclick', (e) => {
    e.preventDefault();
    if (k > 1) { k = 1; x = 0; y = 0; return apply(); }
    const img = box.querySelector('img');
    // Full size: the photo's pixels on the screen's, as far as it is fitted down
    const full = img && img.naturalWidth ? Math.max(img.naturalWidth / img.clientWidth, img.naturalHeight / img.clientHeight) : 4;
    zoomAt(Math.max(full, 2), e);
  });
  new ResizeObserver(apply).observe(box);
}
