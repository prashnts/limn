// The 3D view on part pages. The Blender shot shows first; nothing more loads until asked:
// a small glTF when the pointer comes over it (on a phone, a tap), a big one only from its
// button, which says how big it is. It loads with the shot's own camera, so the first drag
// turns the very picture. Clicking a part names it and links its page (glTF node names are
// page slugs, see build.py).
const root = new URL('..', import.meta.url);
const SMALL = 2e6;                       // bytes: smaller models load on a hover; bigger ones on their button
const LENS = 85, SENSOR = 36, ZOOM = 1.05;   // render/shot.py's camera

document.querySelectorAll('.viewer[data-model]').forEach(el => {
  let started = null;
  const start = () => (started ??= open(el).catch(e => {   // no WebGL, a bad file: keep the picture
    console.warn('3D view:', e);
    el.classList.remove('loading', 'wants');
    el.querySelector('.hint3d')?.remove();
    el.querySelector('.load3d')?.remove();
  }));
  el._start = start;
  const move = el.parentElement.querySelector('[data-move]');
  if (move) {
    if (+el.dataset.bytes >= SMALL) move.textContent += ` · ${Math.round(el.dataset.bytes / 1e6)} MB`;
    move.addEventListener('click', () => { el.classList.add('wants'); move.disabled = true; start(); });
  }
  const button = el.querySelector('.load3d');
  if (button) {
    button.addEventListener('click', e => { e.stopPropagation(); el.classList.add('wants'); start(); });
    return;
  }
  el.addEventListener('pointerenter', e => { if (e.pointerType === 'mouse') start(); });
  el.addEventListener('pointerdown', () => { el.classList.add('wants'); start(); });
});

async function open(el) {
  const hint = el.querySelector('.hint3d');
  el.classList.add('loading');
  const [THREE, { GLTFLoader }, { OrbitControls }, { RoomEnvironment }, pages] = await Promise.all([
    import('three'),
    import('three/addons/loaders/GLTFLoader.js'),
    import('three/addons/controls/OrbitControls.js'),
    import('three/addons/environments/RoomEnvironment.js'),
    fetch(new URL('static/pages.json', root)).then(r => r.json()),
  ]);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  scene.add(key, new THREE.HemisphereLight(0xffffff, 0xb8bec8, 0.6));

  const button = el.querySelector('.load3d');
  const gltf = await new GLTFLoader().loadAsync(el.dataset.model, e => {
    if (button && e.total) button.textContent = `Loading ${Math.round(100 * e.loaded / e.total)} %`;
  });
  button?.remove();
  const model = gltf.scene;
  model.traverse(o => { if (o.isMesh) { o.material.metalness = 0; o.material.roughness = 0.55; } });
  scene.add(model);
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
  const r = size.length() / 2;
  // Blender's: an 85 mm lens on a 36 mm sensor across a 4:3 frame, the bounding sphere fitted
  // to the short side, looking along the 'iso' view (Blender's Z up is glTF's Y up)
  const vfov = 2 * Math.atan(SENSOR * 0.75 / 2 / LENS);
  const fit = 2 * Math.atan(SENSOR / 2 / LENS) * 0.75;
  const camera = new THREE.PerspectiveCamera(THREE.MathUtils.radToDeg(vfov), 4 / 3, r / 100, r * 100);
  // the shot's view (data-dir, three's axes: Blender's x, z, -y): 'iso', or the whole machine's 'front-iso'
  const dir = (el.dataset.dir || '1,0.75,1.25').split(',').map(Number);
  camera.position.copy(center).add(new THREE.Vector3(...dir).normalize().multiplyScalar(r * ZOOM / Math.sin(fit / 2)));
  key.position.copy(camera.position).add(new THREE.Vector3(r, r * 2, 0));
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(center);
  controls.enableDamping = true;
  camera.lookAt(center);

  const resize = () => {
    const w = el.clientWidth, h = el.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(el);
  resize();
  // the shot stays on top until the first drag; the canvas under it already shows the same view
  const poster = el.querySelector('.poster');
  el.classList.remove('loading');
  el.classList.add('live');
  const reveal = () => { poster?.classList.add('gone'); hint?.remove(); };
  controls.addEventListener('start', reveal, { once: true });
  if (el.classList.contains('wants')) reveal();          // a tap that started the loading

  // pick: the nearest ancestor that has a page
  const pick = el.querySelector('.pick');
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  let lit = null, down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;   // a drag, not a click
    const rect = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObject(model, true)[0];
    if (lit) { lit.material.emissive?.setHex(0); lit = null; }
    if (!hit) { pick.hidden = true; return; }
    let o = hit.object;
    while (o && !pages[o.name]) o = o.parent;
    lit = hit.object;
    lit.material = lit.material.clone();
    lit.material.emissive?.setHex(0x2f4f8f);
    if (o) {
      pick.innerHTML = '';
      const a = document.createElement('a');
      a.href = new URL(`parts/${o.name}.html`, root);
      a.textContent = pages[o.name];
      pick.append(a);
      pick.hidden = false;
    }
  });
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  if (el.dataset.motion) await joints(THREE, model, el, reveal);
}

// The joints (models/<slug>.motion.json, guide/motion.py): per joint, for each part that moves
// (by its occurrence path, from the nodes' userData.occ), its change in the model at each recorded
// position. A slider goes through them; between two positions the change is interpolated.
async function joints(THREE, model, el, reveal) {
  const data = await fetch(el.dataset.motion).then(r => r.json());
  model.updateMatrixWorld(true);
  const byPath = new Map();
  model.traverse(o => {
    if (!o.userData?.occ) return;
    const names = [];
    for (let p = o; p && p !== model; p = p.parent) if (p.userData?.occ) names.unshift(p.userData.occ);
    byPath.set(names.join('+'), o);
  });
  const depth = o => { let d = 0; for (let p = o; p; p = p.parent) d++; return d; };
  const box = el.parentElement.querySelector('.motion');
  box.innerHTML = '';
  const m = new THREE.Matrix4(), w = new THREE.Matrix4(), inv = new THREE.Matrix4();
  const pa = new THREE.Vector3(), pb = new THREE.Vector3(), qa = new THREE.Quaternion(), qb = new THREE.Quaternion();
  const sa = new THREE.Vector3(), sb = new THREE.Vector3();
  const at = (list, k) => m.fromArray(list[k]);
  for (const d of data.drives) {
    const parts = Object.entries(d.nodes).map(([p, ms]) => ({ o: byPath.get(p), ms })).filter(x => x.o)
      .sort((a, b) => depth(a.o) - depth(b.o));
    if (!parts.length) continue;
    for (const x of parts) x.rest = x.o.matrixWorld.clone();
    const n = d.values.length;
    const apply = t => {                                 // t: 0..n-1
      const i = Math.min(Math.floor(t), n - 2), f = t - i;
      for (const x of parts) {
        at(x.ms, i).decompose(pa, qa, sa);
        at(x.ms, i + 1).decompose(pb, qb, sb);
        m.compose(pa.lerp(pb, f), qa.slerp(qb, f), sa.lerp(sb, f));
        w.multiplyMatrices(m, x.rest);                   // its place now, in the model
        x.o.parent.updateWorldMatrix(true, false);
        inv.copy(x.o.parent.matrixWorld).invert();
        inv.multiply(w).decompose(x.o.position, x.o.quaternion, x.o.scale);
        x.o.updateMatrixWorld(true);
      }
    };
    const restAt = d.values.reduce((b, v, k) => Math.abs(v - d.rest) < Math.abs(d.values[b] - d.rest) ? k : b, 0);
    const row = document.createElement('div');
    row.className = 'joint';
    row.innerHTML = `<label><span class="jname"></span><input type="range" min="0" max="${(n - 1) * 20}" value="${restAt * 20}"></label>
      <output class="mono"></output><button type="button" class="play" title="Play">▶</button>`;
    row.querySelector('.jname').textContent = d.name;
    const range = row.querySelector('input'), out = row.querySelector('output'), play = row.querySelector('.play');
    const show = () => {
      const t = range.value / 20, i = Math.min(Math.floor(t), n - 2), f = t - i;
      out.textContent = `${(d.values[i] + (d.values[i + 1] - d.values[i]) * f).toFixed(d.unit === 'deg' ? 0 : 1)} ${d.unit === 'deg' ? '°' : 'mm'}`;
      apply(t);
    };
    range.addEventListener('input', () => { reveal(); show(); });
    let anim = null;
    play.addEventListener('click', () => {
      if (anim) { cancelAnimationFrame(anim); anim = null; play.textContent = '▶'; return; }
      reveal();
      play.textContent = '❚❚';
      let dir = 1, last = performance.now();
      const step = now => {
        const v = +range.value + dir * (now - last) / 1000 * range.max / 3;     // the whole range in 3 s
        last = now;
        if (v >= range.max || v <= 0) dir = -dir;
        range.value = Math.max(0, Math.min(range.max, v));
        show();
        anim = requestAnimationFrame(step);
      };
      anim = requestAnimationFrame(step);
    });
    show();
    box.append(row);
  }
  if (!box.children.length) box.innerHTML = '<span class="fine">Nothing of it moves here.</span>';
}

// YouTube thumbnails turn into the player when clicked (nothing from YouTube loads before)
document.querySelectorAll('.yt-play[data-yt]').forEach(a => a.addEventListener('click', e => {
  if (a.dataset.warn && !confirm(`${a.dataset.warn}: play the video?`)) return e.preventDefault();
  e.preventDefault();
  const f = document.createElement('iframe');
  f.src = `https://www.youtube-nocookie.com/embed/${a.dataset.yt}?autoplay=1&rel=0`;
  f.title = a.parentElement.querySelector('figcaption')?.textContent || 'Video';
  f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
  f.allowFullscreen = true;
  a.replaceWith(f);
}));
