// STEP to glTF (.glb) for the guide's 3D views, with OpenCASCADE (occt-import-js, WASM).
//
//   node guide/mesh/mesh.mjs [--coarse] a.step b.step ..   -> a.glb b.glb ..
//   node guide/mesh/mesh.mjs --stl a.step ..                -> a.stl (fine, for printing)
//
// Every STEP node becomes a glTF node with the same name (build.py names the
// products by their page slug, so a click in the viewer finds the page). A file
// whose .glb is newer is skipped. Files are meshed in parallel, one worker each.
import fs from 'node:fs';
import os from 'node:os';
import { createRequire } from 'node:module';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';

const require = createRequire(import.meta.url);

if (isMainThread) {
  const args = process.argv.slice(2);
  const coarse = args.includes('--coarse');
  const ext = args.includes('--stl') ? '.stl' : '.glb';
  const files = args.filter(a => !a.startsWith('--')).filter(f => {
    const o = f.replace(/\.step$/, ext);
    return !fs.existsSync(o) || fs.statSync(o).mtimeMs < fs.statSync(f).mtimeMs;
  });
  // the big ones first, so one doesn't start last and keep everyone waiting
  files.sort((a, b) => fs.statSync(b).size - fs.statSync(a).size);
  const n = Math.min(files.length, Math.max(1, Math.floor(os.cpus().length / 2)), 12);
  let next = 0, failed = 0;
  const run = () => new Promise(done => {
    const go = () => {
      if (next >= files.length) return done();
      const f = files[next++];
      const t = Date.now();
      const w = new Worker(new URL(import.meta.url), { workerData: { f, coarse, ext }, resourceLimits: { maxOldGenerationSizeMb: 8000 } });
      w.on('message', m => console.log(`${((Date.now() - t) / 1000).toFixed(1).padStart(6)}s ${m}`));
      w.on('error', e => { failed++; console.error(`failed ${f}: ${e.message}`); });
      w.on('exit', go);
    };
    go();
  });
  await Promise.all(Array.from({ length: n }, run));
  process.exit(failed ? 1 : 0);
} else {
  const { f, coarse, ext } = workerData;
  const occt = await require('occt-import-js')();
  const r = occt.ReadStepFile(new Uint8Array(fs.readFileSync(f)), ext === '.stl'
    ? { linearUnit: 'millimeter', linearDeflectionType: 'absolute_value', linearDeflection: 0.01, angularDeflection: 0.1 }
    : {
      linearUnit: 'millimeter',
      linearDeflectionType: 'bounding_box_ratio',
      linearDeflection: coarse ? 0.004 : 0.0015,
      angularDeflection: coarse ? 0.6 : 0.35,
    });
  if (!r.success) throw new Error('OpenCASCADE could not read it');
  const out = ext === '.stl' ? toStl(r, f.split('/').pop().replace(/\.step$/, '')) : toGlb(r);
  fs.writeFileSync(f.replace(/\.step$/, ext), out);
  const tris = r.meshes.reduce((s, m) => s + m.index.array.length / 3, 0);
  parentPort.postMessage(`${f.split('/').pop()}: ${r.meshes.length} meshes, ${tris} triangles, ${(out.length / 1e6).toFixed(1)} MB`);
}

// occt's {root: {name, meshes, children}, meshes: [{name, color, attributes, index}]}
// as a binary glTF: one buffer, one material per colour, Z up turned to glTF's Y up.
function toGlb(r) {
  const chunks = [], views = [], accessors = [], meshes = [], materials = [], nodes = [];
  const matOf = new Map();
  let offset = 0;
  const view = (typed, target) => {
    const bytes = new Uint8Array(typed.buffer, typed.byteOffset, typed.byteLength);
    const pad = (4 - (bytes.length % 4)) % 4;
    chunks.push(bytes, new Uint8Array(pad));
    views.push({ buffer: 0, byteOffset: offset, byteLength: bytes.length, target });
    offset += bytes.length + pad;
    return views.length - 1;
  };
  const material = color => {
    const c = color || [0.62, 0.64, 0.68];
    const key = c.map(v => v.toFixed(3)).join(',');
    if (!matOf.has(key)) {
      matOf.set(key, materials.length);
      // STEP colours are sRGB, glTF's are linear
      const lin = c.map(v => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      materials.push({ pbrMetallicRoughness: { baseColorFactor: [...lin, 1], metallicFactor: 0.1, roughnessFactor: 0.7 }, doubleSided: true });
    }
    return matOf.get(key);
  };
  for (const m of r.meshes) {
    const pos = new Float32Array(m.attributes.position.array);
    const nrm = m.attributes.normal ? new Float32Array(m.attributes.normal.array) : null;
    const nv = pos.length / 3;
    const idx = nv < 65536 ? new Uint16Array(m.index.array) : new Uint32Array(m.index.array);
    const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < pos.length; i++) {
      min[i % 3] = Math.min(min[i % 3], pos[i]);
      max[i % 3] = Math.max(max[i % 3], pos[i]);
    }
    const attributes = {};
    accessors.push({ bufferView: view(pos, 34962), componentType: 5126, count: nv, type: 'VEC3', min, max });
    attributes.POSITION = accessors.length - 1;
    if (nrm) {
      accessors.push({ bufferView: view(nrm, 34962), componentType: 5126, count: nv, type: 'VEC3' });
      attributes.NORMAL = accessors.length - 1;
    }
    accessors.push({ bufferView: view(idx, 34963), componentType: nv < 65536 ? 5123 : 5125, count: idx.length, type: 'SCALAR' });
    // no body colour: take the first painted face's
    const faceColor = m.brep_faces?.find(b => b.color)?.color;
    meshes.push({ name: m.name || undefined, primitives: [{ attributes, indices: accessors.length - 1, material: material(m.color || faceColor) }] });
  }
  const node = n => {
    const children = [
      ...n.meshes.map(i => { nodes.push({ mesh: i, name: r.meshes[i].name || undefined }); return nodes.length - 1; }),
      ...n.children.map(node),
    ];
    nodes.push({ name: n.name || undefined, children: children.length ? children : undefined });
    return nodes.length - 1;
  };
  const top = node(r.root);
  nodes.push({ name: 'Z up', children: [top], rotation: [-Math.SQRT1_2, 0, 0, Math.SQRT1_2] });
  const bin = Buffer.concat(chunks);
  const gltf = {
    asset: { version: '2.0', generator: 'limn guide (occt-import-js)' },
    scene: 0, scenes: [{ nodes: [nodes.length - 1] }],
    nodes, meshes, materials, accessors, bufferViews: views,
    buffers: [{ byteLength: bin.length }],
  };
  let json = Buffer.from(JSON.stringify(gltf));
  json = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, 0x20)]);
  const head = Buffer.alloc(12);
  head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4);
  head.writeUInt32LE(12 + 8 + json.length + 8 + bin.length, 8);
  const ch = (len, type) => { const b = Buffer.alloc(8); b.writeUInt32LE(len, 0); b.writeUInt32LE(type, 4); return b; };
  return Buffer.concat([head, ch(json.length, 0x4e4f534a), json, ch(bin.length, 0x004e4942), bin]);
}

// Binary STL, every mesh in one, in mm as modelled (Z up).
function toStl(r, name) {
  const tris = r.meshes.reduce((s, m) => s + m.index.array.length / 3, 0);
  const b = Buffer.alloc(84 + 50 * tris);
  b.write(`limn ${name}`.slice(0, 79), 0, 'ascii');
  b.writeUInt32LE(tris, 80);
  let o = 84;
  for (const m of r.meshes) {
    const p = m.attributes.position.array, ix = m.index.array;
    for (let t = 0; t < ix.length; t += 3) {
      const v = [0, 1, 2].map(k => [p[3 * ix[t + k]], p[3 * ix[t + k] + 1], p[3 * ix[t + k] + 2]]);
      const u = v[1].map((x, k) => x - v[0][k]), w = v[2].map((x, k) => x - v[0][k]);
      const n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
      const l = Math.hypot(...n) || 1;
      for (const x of n) { b.writeFloatLE(x / l, o); o += 4; }
      for (const vv of v) for (const x of vv) { b.writeFloatLE(x, o); o += 4; }
      o += 2;
    }
  }
  return b;
}
