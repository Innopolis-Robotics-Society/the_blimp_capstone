// 3D visualization of the LinkTrack UWB network: anchors, tags, blimp axis.
// Coordinates are UWB hall frame (Z up); the three.js camera is set Z-up too.
import * as THREE from 'three';
import { OrbitControls } from './OrbitControls.js';

const TAG_COLORS = { 1: 0x2bd96f, 2: 0xff9f43 }; // 1 = нос, 2 = корма
const TRAIL_LEN = 500;

// Переменные для записи логов экспериментов (User Story 7)
let isRecording = false;
let recordStartTime = 0;
let recordedData = []; // Сюда будем собирать кадры

// ---------------------------------------------------------------- scene
const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);

const scene = new THREE.Scene();
// Оставляем темный цвет как заглушку, пока грузится картинка
scene.background = new THREE.Color(0x0b0e14);
// Создаем загрузчик текстур
const textureLoader = new THREE.TextureLoader();

textureLoader.load('./static/sky.jpg', function(texture) {
    texture.colorSpace = THREE.SRGBColorSpace;

    // 1. Создаем огромную сферу (радиус 150 метров)
    const skyGeo = new THREE.SphereGeometry(150, 32, 32);

    // 2. Создаем материал
    const skyMat = new THREE.MeshBasicMaterial({
        map: texture,
        side: THREE.BackSide, // ВАЖНО: Рисуем текстуру ВНУТРИ сферы, а не снаружи!
        depthWrite: false     // Чтобы небо всегда было на заднем плане
    });

    const sky = new THREE.Mesh(skyGeo, skyMat);

    // 3. Поворачиваем саму сферу на 90 градусов (компенсируем ваш Z-up)
    sky.rotation.x = Math.PI / 2;

    sky.scale.x = -1

    // Добавляем небо на сцену
    scene.add(sky);
});

const camera = new THREE.PerspectiveCamera(55, 1, 0.05, 200);
camera.up.set(0, 0, 1);
camera.position.set(7, -6, 5);

const controls = new OrbitControls(camera, canvas);
controls.target.set(2, 2, 0);
controls.enableDamping = true;
controls.maxDistance = 30;

scene.add(new THREE.AmbientLight(0xffffff, 0.7));
const sun = new THREE.DirectionalLight(0xffffff, 1.2);
sun.position.set(5, -8, 12);
scene.add(sun);

const grid = new THREE.GridHelper(30, 30, 0x33415c, 0x1c2333);
grid.rotation.x = Math.PI / 2;
scene.add(grid);

// ----- floor -----
const floorTexture = new THREE.TextureLoader().load("./static/floor.png");
floorTexture.colorSpace = THREE.SRGBColorSpace;

const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(30, 30),
    new THREE.MeshBasicMaterial({
        map: floorTexture,
        transparent: true
    })
);

floor.position.set(0, 0, -0.01);
scene.add(floor);
// ------------------

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

// ==========================================================================
// [НОВОЕ] Создаем синего "призрака" симулятора SITL
const sitlBody = new THREE.Mesh(
  new THREE.SphereGeometry(0.8, 24, 16), // Чуть меньше реального дирижабля
  new THREE.MeshStandardMaterial({
    color: 0x4ea1ff,
    transparent: true,
    opacity: 0.35,
    wireframe: true // Делаем его красивой сеткой, как в фантастических фильмах!
  })
);
sitlBody.visible = false; // Скрыт, пока симулятор не пришлет первый кадр
scene.add(sitlBody);
// ==========================================================================

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
// ---------------------------------------------------------------- waypoints (Миссии)
let waypoints = []; // Массив точек миссии
const waypointsGroup = new THREE.Group();
scene.add(waypointsGroup);

const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

// Добавляем точку ДВОЙНЫМ кликом по полу (floor)
canvas.addEventListener('dblclick', (event) => {
  const rect = canvas.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObject(floor);

  if (intersects.length > 0) {
    const hit = intersects[0].point;
    hit.z = 0; // Точка ставится строго на пол
    waypoints.push(hit);
    updateWaypointsVisuals(); // Перерисовываем
  }
});

function updateWaypointsVisuals() {
  waypointsGroup.clear(); // Очищаем 3D объекты маршрута
  const listEl = document.getElementById('wp-list');
  listEl.innerHTML = '';  // Очищаем HTML список на панели

  // Задача 5: Обновление калькулятора параметров пути
  updateRouteStats();

  if (waypoints.length === 0) {
      listEl.innerHTML = '<div style="color: #7f8ca6; font-size: 11px; text-align:center;">Двойной клик по карте<br>для установки точек</div>';
      return;
  }

  // 1. Рисуем 3D-линию.
  const mat = new THREE.LineBasicMaterial({ color: 0xffaa00, linewidth: 2 });
  const geo = new THREE.BufferGeometry().setFromPoints(waypoints);
  const line = new THREE.Line(geo, mat);
  waypointsGroup.add(line);

  // 2. Рисуем 3D-сферы и добавляем HTML-ярлыки с крестиками
  waypoints.forEach((wp, index) => {
    // 3D Сфера
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.1, 16, 16),
      new THREE.MeshStandardMaterial({ color: 0xffaa00, emissive: 0xffaa00 })
    );
    sphere.position.copy(wp);
    waypointsGroup.add(sphere);

    // 3D Подпись P1, P2...
    const label = makeLabel(`P${index + 1}`, '#ffaa00', 0.35);
    label.position.set(wp.x, wp.y, wp.z + 0.3);
    waypointsGroup.add(label);

    // HTML-элемент в панели с КРЕСТИКОМ ✖
    const wpDiv = document.createElement('div');
    wpDiv.className = 'wp-item';
    wpDiv.innerHTML = `
      <span><b>P${index + 1}</b> [${wp.x.toFixed(1)}, ${wp.y.toFixed(1)}]</span>
      <span class="wp-del" onclick="deleteWaypoint(${index})" title="Удалить точку">✖</span>
    `;
    listEl.appendChild(wpDiv);
  });
}

// Задача 5: Функция калькулятора параметров пути (длина и время)
function updateRouteStats() {
  const statsEl = document.getElementById('route-stats');
  if (waypoints.length < 2) {
    statsEl.style.display = 'none';
    return;
  }

  let totalDist = 0;
  for (let i = 1; i < waypoints.length; i++) {
    // Считаем 3D-расстояние между соседними точками вектора
    totalDist += waypoints[i].distanceTo(waypoints[i - 1]);
  }

  // Примерное время полета исходя из средней скорости блимпа ~0.3 м/с
  const estTime = Math.round(totalDist / 0.3);

  statsEl.textContent = `Длина: ${totalDist.toFixed(2)} м | Время: ~${estTime} сек`;
  statsEl.style.display = 'block';
}

// Глобальная функция для удаления точки (крестик вызывает её по index)
window.deleteWaypoint = (index) => {
  waypoints.splice(index, 1); // Магия здесь: splice вырезает ровно 1 точку
  updateWaypointsVisuals();   // При перерисовке линии соседи соединятся сами
};

// Глобальная функция очистки всего маршрута
window.clearWaypoints = () => {
  waypoints = [];
  updateWaypointsVisuals();
};

// Глобальная функция отправки на сервер
window.sendMission = () => {
  if (waypoints.length === 0) return alert("Добавьте точки маршрута!");

  const missionData = waypoints.map(wp => ({ x: wp.x, y: wp.y, z: wp.z }));

  fetch('/upload_route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(missionData)
  }).then(res => {
    if(res.ok) {
        // Меняем цвет линии на зеленый в знак успеха
        waypointsGroup.children[0].material.color.setHex(0x2bd96f);
    }
  }).catch(err => console.error(err));
};

// Инициализация пустой панели при старте
updateWaypointsVisuals();
// ----------------------------------------------------------------

// ---------------------------------------------------------------- frames
let frameCount = 0, lastVoltage = null;

function handleFrame(f) {
  // --- [НОВОЕ] Отрисовка симулятора ---
  if (f.frame_type === 'sitl_frame') {
    // Двигаем синий каркасный шар в позицию, которую прислал SITL
    sitlBody.position.set(f.x, f.y, f.z);
    sitlBody.visible = true;

    // Обновляем режим полетника на левой панели
    if (f.mode) {
      document.getElementById('control-mode').textContent = `${f.mode} (СИМУЛЯТОР)`;
      document.getElementById('control-mode').style.color = '#4ea1ff';
    }
    return; // Выходим, так как в этом кадре нет UWB-тегов
  }
  // 1. Обновляем статус режима полета на дашборде (если автопилот прислал данные)
  const mode = f.mode || f.flight_mode;
  if (mode) {
    const modeEl = document.getElementById('control-mode');
    if (['MANUAL', 'STABILIZE', 'ALT_HOLD'].includes(mode)) {
      modeEl.textContent = `${mode} (ПИЛОТ)`;
      modeEl.style.color = '#4ea1ff'; // Синий для ручного контроля
    } else if (['GUIDED', 'AUTO'].includes(mode)) {
      modeEl.textContent = `${mode} (АВТОПИЛОТ)`;
      modeEl.style.color = '#2bd96f'; // Зеленый для автономии
    } else {
      modeEl.textContent = mode;
      modeEl.style.color = '#e8eefc';
    }
  }

  // 2. Если это системный кадр, а не координаты — дальше не идем
  if (f.frame_type !== 'anchorframe0') return;

  // ==========================================================
  // НАСТРОЙКА ДЛЯ ОТЧЕТА: Фейковый подъем дирижабля (в метрах)
  // Установите значение 0.0, когда закончите делать скриншоты!
  const FAKE_Z_OFFSET = 1.5;
  // ==========================================================

  frameCount++;
  lastVoltage = f.voltage;

  const alpha = Number(document.getElementById('opt-ema').value);
  const currentMode = document.getElementById('control-mode').textContent || '—';
  const elapsedSeconds = isRecording ? ((Date.now() - recordStartTime) / 1000).toFixed(3) : '0';
  const present = new Set();

  // 3. Единый цикл: обрабатываем метки сразу и для 3D-карты, и для записи CSV-лога
  for (const n of f.nodes ?? []) {
    if (n.role !== 2) continue; // Работаем только с метками (Tag)

    present.add(n.id);
    const tag = tags.get(n.id) ?? makeTag(n.id);

    // ПРИМЕНЯЕМ ПОДЪЕМ ДЛЯ ОТЧЕТА:
    // Поднимаем ось Z (индекс 2 в массиве) до всех вычислений.
    // Благодаря этому дирижабль поднимется и на экране, и в записанном CSV-файле!
    n.pos_3d[2] += FAKE_Z_OFFSET;

    // --- ЛОГИРОВАНИЕ ---
    if (isRecording) {
      recordedData.push([
        elapsedSeconds,
        n.id,
        n.pos_3d[0].toFixed(3), // X
        n.pos_3d[1].toFixed(3), // Y
        n.pos_3d[2].toFixed(3), // Z
        lastVoltage !== null ? lastVoltage.toFixed(2) : '',
        currentMode
      ]);
    }

    // --- 3D ВИЗУАЛИЗАЦИЯ ---
    const p = new THREE.Vector3(...n.pos_3d);

    // Сглаживание координат (EMA-фильтр)
    tag.pos = tag.pos ? tag.pos.lerp(p, alpha) : p;
    tag.lastDis = n.dis_arr;

    // Перемещаем 3D-сферу и текстовую метку
    tag.mesh.position.copy(tag.pos);
    tag.label.position.set(tag.pos.x, tag.pos.y, tag.pos.z + 0.22);

    // Рисуем трейл (хвост маршрута) каждый 3-й кадр для оптимизации
    if (document.getElementById('opt-trails').checked && frameCount % 3 === 0) {
      pushTrail(tag, tag.pos);
    }
  }

  // 4. Обновляем счетчики видимости меток (статистика в левой панели)
  for (const [id, tag] of tags) {
    tag.total++;
    if (present.has(id)) tag.seen++;
  }

  // 5. Перерисовываем составные объекты на основе новых координат
  updateBlimp();  // Отрисовка корпуса дирижабля между носом и кормой
  updateRanges(); // Отрисовка линий дальностей к якорям
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

// Обработчик кнопки записи лога теста
const btnRecord = document.getElementById('btn-record');
const inputNotes = document.getElementById('log-notes');

btnRecord.addEventListener('click', () => {
  if (!isRecording) {
    // ЗАПУСК ЗАПИСИ
    isRecording = true;
    recordStartTime = Date.now();
    recordedData = []; // Очищаем старые данные

    btnRecord.textContent = '■ Остановить и скачать';
    btnRecord.style.background = '#e05252'; // Красный цвет кнопки
    btnRecord.style.color = '#white';
    inputNotes.disabled = true; // Блокируем поле ввода во время теста
    console.log("Запись эксперимента запущена...");
  } else {
    // ОСТАНОВКА ЗАПИСИ И СКАЧИВАНИЕ
    isRecording = false;
    btnRecord.textContent = '● Начать запись';
    btnRecord.style.background = '#1d2636';
    btnRecord.style.color = '#e8eefc';
    inputNotes.disabled = false; // Разблокируем поле ввода

    console.log("Запись остановлена. Генерируем CSV...");
    downloadCSV();
  }
});

// Функция генерации и автоматического скачивания CSV файла браузером
function downloadCSV() {
  if (recordedData.length === 0) {
    alert("Нет данных для сохранения! Возможно, дирижабль не прислал ни одного кадра.");
    return;
  }

  const notes = inputNotes.value.trim() || "без_заметки";

  let csvContent = "";
  // Добавляем метаданные в шапку файла
  csvContent += `# Эксперимент: ${notes}\r\n`;
  csvContent += `# Дата записи: ${new Date().toLocaleString()}\r\n`;
  csvContent += "Time_s,Tag_ID,X_m,Y_m,Z_m,Voltage_V,Flight_Mode\r\n";

  recordedData.forEach(row => {
    csvContent += row.join(",") + "\r\n";
  });

  // Добавляем маркер BOM (\ufeff), чтобы Excel на Windows корректно читал русские буквы в заметках
  const blob = new Blob(["\ufeff" + csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");

  // Очищаем имя файла от недопустимых символов
  const cleanNotes = notes.replace(/[^a-z0-9а-яё\s-_]/gi, '').replace(/\s+/g, '_');
  const filename = `blimp_test_${cleanNotes}_${Date.now()}.csv`;

  link.setAttribute("href", url);
  link.setAttribute("download", filename);
  document.body.appendChild(link);

  link.click(); // Запускаем скачивание в браузере
  document.body.removeChild(link);
}

// ---------------------------------------------------------------- HUD (Обновление каждые 500мс)
setInterval(() => {
  const currentRate = frameCount / 0.5;
  document.getElementById('rate').textContent = `${currentRate.toFixed(0)} Гц`;

  // --- Задача 2: Аварийный светофор Failsafe ---
  const banner = document.getElementById('failsafe-banner');
  let failsafeMsg = "";

  if (currentRate === 0) {
    // Если за полсекунды не пришло ни одного пакета UWB
    failsafeMsg = "⚠️ ACCIDENT: UWB CONNECTION LOSS";
  } else if (lastVoltage !== null && lastVoltage > 1.0 && lastVoltage < 7.00) {
    // Если батарея дирижабля 2S разряжена ниже 7.0 Вольт
    failsafeMsg = "⚠️ ACCIDENT: LOW BATTERY CHARGE 2S";
  }

  if (failsafeMsg) {
    banner.textContent = failsafeMsg;
    banner.style.display = 'block';
  } else {
    banner.style.display = 'none';
  }
  // --------------------------------------------

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

// --- Новые команды прямого пилотирования (светофорная индикация) ---
window.armBlimp = () => {
  const btn = document.getElementById('btn-arm');

  fetch('/action/arm', { method: 'POST' })
    .then(res => {
      if (res.ok) {
        // Успех: перекрашиваем кнопку в зеленый, делаем текст читаемым
        btn.style.background = '#2bd96f';
        btn.style.color = '#0b0e14';
      } else {
        alert("Не удалось завести моторы (проверьте связь с SITL)!");
      }
    })
    .catch(err => alert("Ошибка связи с сервером!"));
};

window.takeoffBlimp = () => {
  const btn = document.getElementById('btn-takeoff');

  fetch('/action/takeoff', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ alt: 1.2 }) // Взлет на высоту 1.2 метра
  })
    .then(res => {
      if (res.ok) {
        // Успех: перекрашиваем кнопку в зеленый
        btn.style.background = '#2bd96f';
        btn.style.color = '#0b0e14';
      } else {
        alert("Не удалось отправить команду взлета!");
      }
    })
    .catch(err => alert("Ошибка связи с сервером!"));
};