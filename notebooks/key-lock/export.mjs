import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire('/home/noop/repo/projects/site/mesh/mesh.mjs');
const occt = await require('occt-import-js')();
const [file, out, ...bodies] = process.argv.slice(2);
const r = occt.ReadStepFile(new Uint8Array(fs.readFileSync(file)),
  { linearUnit: 'millimeter', linearDeflectionType: 'absolute_value', linearDeflection: 0.03, angularDeflection: 0.2 });
const res = {};
for (const b of bodies.map(Number)) {
  const m = r.meshes[b];
  res[b] = { name: m.name, p: Array.from(m.attributes.position.array), i: Array.from(m.index.array) };
}
fs.writeFileSync(out, JSON.stringify(res));
for (const b in res) console.log(b, res[b].name, res[b].i.length / 3, 'tris');
