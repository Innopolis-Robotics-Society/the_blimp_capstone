// 3D visualization of the LinkTrack UWB network: anchors, tags, blimp axis.
// Coordinates are UWB hall frame (Z up); the three.js camera is set Z-up too.
import * as THREE from 'three';
import { OrbitControls } from './OrbitControls.js';

const TAG_COLORS = { 1: 0x2bd96f, 2: 0xff9f43 }; // 1 = нос, 2 = корма
const TRAIL_LEN = 500;

// ---------------------------------------------------------------- scene
const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0e14);

const camera = new THREE.PerspectiveCamera(55, 1, 0.05, 200);
camera.up.set(0, 0, 1);
camera.position.set(7, -6, 5);

const controls = new OrbitControls(camera, canvas);
controls.target.set(2, 2, 0);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.7));
const sun = new THREE.DirectionalLight(0xffffff, 1.2);
sun.position.set(5, -8, 12);
scene.add(sun);

const grid = new THREE.GridHelper(30, 30, 0x33415c, 0x1c2333);
grid.rotation.x = Math.PI / 2; // default grid lies in XZ; rotate into XY floor
scene.add(grid);
scene.add(new THREE.AxesHelper(1.2));

function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

function makeLabel(text, color = '#e8eefc', scale = 0.5) {
  const cv = document.createElement('canvas');
  cv.width = 256; cv.height = 96;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(cv), depthTest: false, transparent: true,
  }));
  sprite.scale.set(scale * 2.6, scale, 1);
  sprite.userData.draw = (t) => {
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.font = 'bold 44px system-ui, sans-serif';
    ctx.fillStyle = color;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(t, cv.width / 2, cv.height / 2);
    sprite.material.map.needsUpdate = true;
  };
  sprite.userData.draw(text);
  return sprite;
}

// ---------------------------------------------------------------- anchors
let anchorsCfg = [];               // [{id, pos:[x,y,z]}]
const anchorsGroup = new THREE.Group();
scene.add(anchorsGroup);

function rebuildAnchors() {
  anchorsGroup.clear();
  for (const a of anchorsCfg) {
    const cube = new THREE.Mesh(
      new THREE.BoxGeometry(0.16, 0.16, 0.16),
      new THREE.MeshStandardMaterial({ color: 0x4ea1ff }));
    cube.position.set(...a.pos);
    const label = makeLabel(`A${a.id}`, '#4ea1ff');
    label.position.set(a.pos[0], a.pos[1], a.pos[2] + 0.28);
    anchorsGroup.add(cube, label);
  }
  const c = anchorsCfg.reduce((s, a) => s.add(new THREE.Vector3(...a.pos)),
                              new THREE.Vector3());
  if (anchorsCfg.length) controls.target.copy(c.divideScalar(anchorsCfg.length));
}

function renderAnchorEditor() {
  const tbl = document.getElementById('anchors-tbl');
  tbl.innerHTML = '<tr><td></td><td>x</td><td>y</td><td>z</td></tr>';
  for (const a of anchorsCfg) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>A${a.id}</td>` + [0, 1, 2].map(i =>
      `<td><input type="number" step="0.1" value="${a.pos[i]}"
           data-id="${a.id}" data-axis="${i}"></td>`).join('');
    tbl.appendChild(tr);
  }
}

async function loadAnchors() {
  const resp = await fetch('/api/anchors');
  anchorsCfg = (await resp.json()).anchors;
  rebuildAnchors();
  renderAnchorEditor();
}

document.getElementById('btn-save').addEventListener('click', async () => {
  for (const inp of document.querySelectorAll('#anchors-tbl input')) {
    const a = anchorsCfg.find(x => x.id === Number(inp.dataset.id));
    a.pos[Number(inp.dataset.axis)] = Number(inp.value) || 0;
  }
  const resp = await fetch('/api/anchors', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ anchors: anchorsCfg }),
  });
  document.getElementById('save-status').textContent = resp.ok ? '✓' : '✗ ошибка';
  setTimeout(() => document.getElementById('save-status').textContent = '', 2000);
  rebuildAnchors();
});

// ---------------------------------------------------------------- tags
const tags = new Map(); // id -> {mesh,label,trail,trailPts,trailIdx,pos,seen,total,lastDis}

function makeTag(id) {
  const color = TAG_COLORS[id] ?? 0x9aa7c1;
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(0.09, 24, 16),
    new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.35 }));
  const label = makeLabel(`T${id}`, '#' + color.toString(16).padStart(6, '0'));
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute('position',
    new THREE.BufferAttribute(new Float32Array(TRAIL_LEN * 3), 3));
  trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(trailGeo,
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.55 }));
  trail.frustumCulled = false;
  scene.add(mesh, label, trail);
  const tag = { mesh, label, trail, trailPts: 0, trailIdx: 0,
                pos: null, seen: 0, total: 0, lastDis: [] };
  tags.set(id, tag);
  return tag;
}

function pushTrail(tag, p) {
  const attr = tag.trail.geometry.attributes.position;
  attr.setXYZ(tag.trailIdx, p.x, p.y, p.z);
  tag.trailIdx = (tag.trailIdx + 1) % TRAIL_LEN;
  tag.trailPts = Math.min(tag.trailPts + 1, TRAIL_LEN);
  // draw oldest..newest without a seam: simplest is full range once wrapped
  tag.trail.geometry.setDrawRange(0, tag.trailPts);
  attr.needsUpdate = true;
}

// blimp axis: ellipsoid + heading arrow between tag 1 (нос) and tag 2 (корма)
const blimpBody = new THREE.Mesh(
  new THREE.SphereGeometry(1, 24, 16),
  new THREE.MeshStandardMaterial({ color: 0x8f6fff, transparent: true, opacity: 0.22 }));
const blimpArrow = new THREE.ArrowHelper(
  new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 0.7, 0x8f6fff, 0.22, 0.12);
blimpBody.visible = blimpArrow.visible = false;
scene.add(blimpBody, blimpArrow);

function updateBlimp() {
  const nose = tags.get(1)?.pos, stern = tags.get(2)?.pos;
  const ok = nose && stern;
  blimpBody.visible = blimpArrow.visible = ok;
  if (!ok) return;
  const dir = new THREE.Vector3().subVectors(nose, stern);
  const len = Math.max(dir.length(), 0.2);
  const mid = new THREE.Vector3().addVectors(nose, stern).multiplyScalar(0.5);
  blimpBody.position.copy(mid);
  blimpBody.scale.set(len / 2 + 0.12, 0.25, 0.25);
  blimpBody.setRotationFromQuaternion(new THREE.Quaternion()
    .setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir.clone().normalize()));
  blimpArrow.position.copy(nose);
  blimpArrow.setDirection(dir.normalize());
}

// range lines tag -> anchor, with distance labels
const rangesGroup = new THREE.Group();
scene.add(rangesGroup);
const rangeLines = new Map(); // "tag:anchor" -> {line, label}

function updateRanges() {
  const show = document.getElementById('opt-ranges').checked;
  rangesGroup.visible = show;
  if (!show) return;
  const used = new Set();
  for (const [tid, tag] of tags) {
    if (!tag.pos) continue;
    for (const a of anchorsCfg) {
      const dis = tag.lastDis[a.id];
      if (!dis) continue; // 0 = no ranging to this anchor
      const key = `${tid}:${a.id}`;
      used.add(key);
      let rl = rangeLines.get(key);
      if (!rl) {
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
        const line = new THREE.Line(geo, new THREE.LineDashedMaterial({
          color: 0x5a6a8a, dashSize: 0.12, gapSize: 0.08,
          transparent: true, opacity: 0.7 }));
        line.frustumCulled = false;
        const label = makeLabel('', '#7f8ca6', 0.28);
        rangesGroup.add(line, label);
        rl = { line, label, lastText: '' };
        rangeLines.set(key, rl);
      }
      const ap = new THREE.Vector3(...a.pos);
      const attr = rl.line.geometry.attributes.position;
      attr.setXYZ(0, tag.pos.x, tag.pos.y, tag.pos.z);
      attr.setXYZ(1, ap.x, ap.y, ap.z);
      attr.needsUpdate = true;
      rl.line.computeLineDistances();
      rl.label.position.lerpVectors(tag.pos, ap, 0.5);
      const text = dis.toFixed(2);
      if (text !== rl.lastText) { rl.label.userData.draw(text); rl.lastText = text; }
      rl.line.visible = rl.label.visible = true;
    }
  }
  for (const [key, rl] of rangeLines) {
    if (!used.has(key)) rl.line.visible = rl.label.visible = false;
  }
}

// ---------------------------------------------------------------- frames
let frameCount = 0, lastVoltage = null;

function handleFrame(f) {
  if (f.frame_type !== 'anchorframe0') return;
  frameCount++;
  lastVoltage = f.voltage;
  const alpha = Number(document.getElementById('opt-ema').value);
  const present = new Set();
  for (const n of f.nodes ?? []) {
    if (n.role !== 2) continue; // TAG
    present.add(n.id);
    const tag = tags.get(n.id) ?? makeTag(n.id);
    const p = new THREE.Vector3(...n.pos_3d);
    tag.pos = tag.pos ? tag.pos.lerp(p, alpha) : p;
    tag.lastDis = n.dis_arr;
    tag.mesh.position.copy(tag.pos);
    tag.label.position.set(tag.pos.x, tag.pos.y, tag.pos.z + 0.22);
    if (document.getElementById('opt-trails').checked && frameCount % 3 === 0)
      pushTrail(tag, tag.pos);
  }
  for (const [id, tag] of tags) {
    tag.total++;
    if (present.has(id)) tag.seen++;
  }
  updateBlimp();
  updateRanges();
}

document.getElementById('opt-trails').addEventListener('change', (e) => {
  for (const tag of tags.values()) tag.trail.visible = e.target.checked;
});
document.getElementById('btn-clear').addEventListener('click', () => {
  for (const tag of tags.values()) {
    tag.trailPts = tag.trailIdx = 0;
    tag.trail.geometry.setDrawRange(0, 0);
  }
});
document.getElementById('opt-ema').addEventListener('input', (e) => {
  document.getElementById('ema-val').textContent = Number(e.target.value).toFixed(2);
});

// ---------------------------------------------------------------- HUD
setInterval(() => {
  document.getElementById('rate').textContent = `${(frameCount / 0.5).toFixed(0)} Гц`;
  frameCount = 0;
  document.getElementById('voltage').textContent =
    lastVoltage == null ? '— В' : `${lastVoltage.toFixed(2)} В`;
  const el = document.getElementById('tags');
  el.innerHTML = '';
  for (const [id, tag] of [...tags].sort((a, b) => a[0] - b[0])) {
    if (!tag.pos) continue;
    const card = document.createElement('div');
    card.className = 'tag-card';
    const color = '#' + (TAG_COLORS[id] ?? 0x9aa7c1).toString(16).padStart(6, '0');
    card.style.borderLeftColor = color;
    const pct = tag.total ? (100 * tag.seen / tag.total).toFixed(0) : '—';
    card.innerHTML =
      `<div class="row"><span style="color:${color}">T${id} ${id === 1 ? 'нос' : id === 2 ? 'корма' : ''}</span>` +
      `<span class="val">видим ${pct}%</span></div>` +
      `<div class="row"><span>x y z</span><span class="val">` +
      `${tag.pos.x.toFixed(2)} ${tag.pos.y.toFixed(2)} ${tag.pos.z.toFixed(2)}</span></div>`;
    el.appendChild(card);
  }
}, 500);

// ---------------------------------------------------------------- websocket
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  const dot = document.getElementById('ws-dot');
  ws.onopen = () => dot.classList.add('ok');
  ws.onmessage = (e) => handleFrame(JSON.parse(e.data));
  ws.onclose = () => { dot.classList.remove('ok'); setTimeout(connect, 1000); };
  ws.onerror = () => ws.close();
}
connect();
loadAnchors();

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});
