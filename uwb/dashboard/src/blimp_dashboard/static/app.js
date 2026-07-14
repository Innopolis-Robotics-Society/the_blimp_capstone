(function () {
  'use strict';

  var TRAIL_LIMIT = 700;
  var UWB_STALE_MS = 2500;

  function byId(id) {
    return document.getElementById(id);
  }

  var ui = {
    wsDot: byId('ws-dot'),
    wsState: byId('ws-state'),
    uwbDot: byId('uwb-dot'),
    uwbState: byId('uwb-state'),
    mavDot: byId('mav-dot'),
    mavState: byId('mav-state'),
    alert: byId('alert'),
    configuredTag: byId('configured-tag'),
    activeTag: byId('active-tag'),
    tagX: byId('tag-x'),
    tagY: byId('tag-y'),
    tagZ: byId('tag-z'),
    uwbRate: byId('uwb-rate'),
    uwbVoltage: byId('uwb-voltage'),
    uwbAge: byId('uwb-age'),
    showTrail: byId('show-trail'),
    showRanges: byId('show-ranges'),
    ema: byId('ema'),
    emaValue: byId('ema-value'),
    clearTrail: byId('clear-trail'),
    anchorsBody: document.querySelector('#anchors-table tbody'),
    reloadAnchors: byId('reload-anchors'),
    saveAnchors: byId('save-anchors'),
    anchorStatus: byId('anchor-status'),
    map: byId('map'),
    arm: byId('arm'),
    disarm: byId('disarm'),
    flightMode: byId('flight-mode'),
    setMode: byId('set-mode'),
    commandStatus: byId('command-status'),
    waypointX: byId('wp-x'),
    waypointY: byId('wp-y'),
    waypointZ: byId('wp-z'),
    addWaypoint: byId('add-waypoint'),
    waypointList: byId('waypoint-list'),
    routeStats: byId('route-stats'),
    clearWaypoints: byId('clear-waypoints'),
    uploadMission: byId('upload-mission'),
    startMission: byId('start-mission'),
    missionStatus: byId('mission-status'),
    recordNote: byId('record-note'),
    record: byId('record'),
    recordStatus: byId('record-status')
  };

  var state = {
    ws: null,
    wsConnected: false,
    wsOpenedAt: 0,
    reconnectTimer: null,
    configuredTagId: null,
    activeTagId: null,
    rawPosition: null,
    position: null,
    distances: [],
    trail: [],
    lastUwbAt: 0,
    windowFrames: 0,
    voltage: null,
    anchors: [],
    waypoints: [],
    mapView: null,
    mavConnected: false,
    mavStatusKnown: false,
    mavStatusPollBusy: false,
    commandBusy: false,
    missionUploaded: false,
    routeRevision: 0,
    recording: false,
    recordStartedAt: 0,
    recordRows: []
  };

  function finiteNumber(value) {
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function validPosition(pos) {
    return Array.isArray(pos) && pos.length >= 3 &&
      finiteNumber(pos[0]) !== null &&
      finiteNumber(pos[1]) !== null &&
      finiteNumber(pos[2]) !== null;
  }

  function setPanelStatus(element, message, kind) {
    element.textContent = message;
    element.classList.remove('good', 'bad', 'warning');
    if (kind) {
      element.classList.add(kind);
    }
  }

  function detailText(value) {
    if (typeof value === 'string') {
      return value;
    }
    if (Array.isArray(value)) {
      return value.map(detailText).join('; ');
    }
    if (value && typeof value === 'object') {
      if (typeof value.msg === 'string') {
        return value.msg;
      }
      try {
        return JSON.stringify(value);
      } catch (error) {
        return 'Неизвестная ошибка';
      }
    }
    return '';
  }

  function responseMessage(data, fallback) {
    if (!data || typeof data !== 'object') {
      return fallback;
    }
    return detailText(data.message) || detailText(data.detail) || fallback;
  }

  async function apiRequest(path, options) {
    var response = await fetch(path, options || {});
    var text = await response.text();
    var data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = { detail: text };
      }
    }
    if (!response.ok) {
      var requestError = new Error(responseMessage(data, 'HTTP ' + response.status));
      requestError.status = response.status;
      requestError.data = data;
      throw requestError;
    }
    return data;
  }

  function jsonPost(path, body) {
    var options = {
      method: 'POST',
      headers: { 'X-Blimp-Control': 'dashboard' }
    };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    return apiRequest(path, options);
  }

  function resetTrackedTag() {
    state.rawPosition = null;
    state.position = null;
    state.distances = [];
    state.trail = [];
    state.lastUwbAt = 0;
    state.windowFrames = 0;
    state.voltage = null;
    ui.activeTag.textContent = state.activeTagId === null ? 'ожидание' : 'T' + state.activeTagId;
    ui.tagX.textContent = '—';
    ui.tagY.textContent = '—';
    ui.tagZ.textContent = '—';
    ui.uwbVoltage.textContent = '— В';
    drawMap();
  }

  async function loadDashboardConfig() {
    try {
      var data = await apiRequest('/api/config', { cache: 'no-store' });
      var id = Number(data.uwb_tag_id);
      if (!Number.isInteger(id) || id < 0 || id > 255) {
        throw new Error('сервер не вернул допустимый uwb_tag_id');
      }
      state.configuredTagId = id;
      state.activeTagId = id;
      ui.configuredTag.textContent = 'T' + id;
      if (data.mission_limits && typeof data.mission_limits === 'object') {
        var minAltitude = finiteNumber(data.mission_limits.min_altitude);
        var maxAltitude = finiteNumber(data.mission_limits.max_altitude);
        if (minAltitude !== null) {
          ui.waypointZ.min = String(minAltitude);
        }
        if (maxAltitude !== null) {
          ui.waypointZ.max = String(maxAltitude);
        }
      }
      resetTrackedTag();
    } catch (error) {
      state.configuredTagId = null;
      state.activeTagId = null;
      ui.configuredTag.textContent = 'первая метка';
      ui.configuredTag.title = 'Config API недоступен: ' + error.message;
    }
    updateRealtimeStatus();
  }

  function candidatesFromFrame(frame) {
    if (!frame || typeof frame !== 'object') {
      return [];
    }
    if (frame.frame_type === 'anchorframe0') {
      return Array.isArray(frame.nodes)
        ? frame.nodes.filter(function (node) {
          return node && Number(node.role) === 2 && validPosition(node.pos_3d);
        })
        : [];
    }
    if (frame.frame_type === 'tagframe0' && Number(frame.role) === 2 && validPosition(frame.pos_3d)) {
      return [frame];
    }
    return [];
  }

  function handleUwbFrame(frame) {
    if (!frame) {
      return;
    }

    var candidates = candidatesFromFrame(frame);
    if (!candidates.length) {
      return;
    }

    if (state.activeTagId === null) {
      candidates.sort(function (left, right) {
        return Number(left.id) - Number(right.id);
      });
      state.activeTagId = Number(candidates[0].id);
    }

    var node = candidates.find(function (candidate) {
      return Number(candidate.id) === state.activeTagId;
    });
    if (!node) {
      return;
    }

    var raw = {
      x: Number(node.pos_3d[0]),
      y: Number(node.pos_3d[1]),
      z: Number(node.pos_3d[2])
    };
    var alpha = Number(ui.ema.value);

    state.rawPosition = raw;
    if (state.position) {
      state.position = {
        x: state.position.x + alpha * (raw.x - state.position.x),
        y: state.position.y + alpha * (raw.y - state.position.y),
        z: state.position.z + alpha * (raw.z - state.position.z)
      };
    } else {
      state.position = { x: raw.x, y: raw.y, z: raw.z };
    }

    state.distances = Array.isArray(node.dis_arr) ? node.dis_arr.slice() : [];
    state.lastUwbAt = Date.now();
    state.windowFrames += 1;

    var voltage = finiteNumber(frame.voltage);
    if (voltage !== null) {
      state.voltage = voltage;
    }

    state.trail.push({ x: state.position.x, y: state.position.y });
    if (state.trail.length > TRAIL_LIMIT) {
      state.trail.splice(0, state.trail.length - TRAIL_LIMIT);
    }

    if (state.recording) {
      state.recordRows.push([
        ((Date.now() - state.recordStartedAt) / 1000).toFixed(3),
        state.activeTagId,
        raw.x.toFixed(4),
        raw.y.toFixed(4),
        raw.z.toFixed(4),
        state.voltage === null ? '' : state.voltage.toFixed(3)
      ]);
      setPanelStatus(ui.recordStatus, 'Записано пакетов: ' + state.recordRows.length, 'good');
    }

    updateTagReadout();
    drawMap();
  }

  function updateTagReadout() {
    ui.activeTag.textContent = state.activeTagId === null ? 'ожидание' : 'T' + state.activeTagId;
    if (!state.position) {
      return;
    }
    ui.tagX.textContent = state.position.x.toFixed(2);
    ui.tagY.textContent = state.position.y.toFixed(2);
    ui.tagZ.textContent = state.position.z.toFixed(2);
    ui.uwbVoltage.textContent = state.voltage === null ? '— В' : state.voltage.toFixed(2) + ' В';
  }

  function setAlert(message) {
    ui.alert.textContent = message || '';
    ui.alert.classList.toggle('visible', Boolean(message));
  }

  function updateRealtimeStatus() {
    var now = Date.now();
    var age = state.lastUwbAt ? now - state.lastUwbAt : Infinity;
    var fresh = age < UWB_STALE_MS;
    var rate = state.windowFrames * 2;
    state.windowFrames = 0;

    ui.uwbRate.textContent = rate.toFixed(0) + ' Гц';
    ui.uwbAge.textContent = Number.isFinite(age) ? (age / 1000).toFixed(1) + ' с назад' : '—';
    ui.uwbDot.classList.toggle('ok', fresh);

    if (fresh) {
      ui.uwbState.textContent = 'UWB: T' + state.activeTagId;
    } else if (state.activeTagId !== null) {
      ui.uwbState.textContent = 'UWB: нет T' + state.activeTagId;
    } else {
      ui.uwbState.textContent = 'UWB: ожидание метки';
    }

    if (!state.wsConnected) {
      setAlert('Нет соединения с потоком данных дашборда.');
    } else if (now - state.wsOpenedAt > UWB_STALE_MS && !fresh) {
      var target = state.activeTagId === null ? 'выбранной метки' : 'метки T' + state.activeTagId;
      setAlert('Нет свежих UWB-данных от ' + target + '.');
    } else {
      setAlert('');
    }
  }

  function renderAnchors() {
    ui.anchorsBody.innerHTML = '';
    state.anchors.forEach(function (anchor) {
      var row = document.createElement('tr');
      var idCell = document.createElement('td');
      idCell.textContent = 'A' + anchor.id;
      row.appendChild(idCell);

      [0, 1, 2].forEach(function (axis) {
        var cell = document.createElement('td');
        var input = document.createElement('input');
        input.type = 'number';
        input.step = '0.1';
        input.value = String(anchor.pos[axis]);
        input.dataset.anchorId = String(anchor.id);
        input.dataset.axis = String(axis);
        cell.appendChild(input);
        row.appendChild(cell);
      });
      ui.anchorsBody.appendChild(row);
    });
    drawMap();
  }

  async function loadAnchors() {
    setPanelStatus(ui.anchorStatus, 'Загрузка координат якорей…', null);
    try {
      var data = await apiRequest('/api/anchors', { cache: 'no-store' });
      if (!data || !Array.isArray(data.anchors)) {
        throw new Error('Сервер вернул неверный формат anchors');
      }
      state.anchors = data.anchors.map(function (anchor) {
        return {
          id: Number(anchor.id),
          pos: [Number(anchor.pos[0]), Number(anchor.pos[1]), Number(anchor.pos[2])]
        };
      });
      renderAnchors();
      setPanelStatus(ui.anchorStatus, 'Загружено якорей: ' + state.anchors.length + '.', 'good');
    } catch (error) {
      setPanelStatus(ui.anchorStatus, 'Не удалось загрузить якоря: ' + error.message, 'bad');
    }
  }

  async function saveAnchors() {
    var next = state.anchors.map(function (anchor) {
      return { id: anchor.id, pos: anchor.pos.slice() };
    });
    var inputs = ui.anchorsBody.querySelectorAll('input[data-anchor-id]');

    for (var index = 0; index < inputs.length; index += 1) {
      var input = inputs[index];
      var anchorId = Number(input.dataset.anchorId);
      var axis = Number(input.dataset.axis);
      var value = finiteNumber(input.value);
      if (value === null) {
        setPanelStatus(ui.anchorStatus, 'Все координаты якорей должны быть числами.', 'bad');
        return;
      }
      var target = next.find(function (anchor) {
        return anchor.id === anchorId;
      });
      if (target) {
        target.pos[axis] = value;
      }
    }

    ui.saveAnchors.disabled = true;
    setPanelStatus(ui.anchorStatus, 'Сохранение…', null);
    try {
      var data = await apiRequest('/api/anchors', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anchors: next })
      });
      state.anchors = data.anchors;
      renderAnchors();
      setPanelStatus(ui.anchorStatus, 'Координаты якорей сохранены.', 'good');
    } catch (error) {
      setPanelStatus(ui.anchorStatus, 'Ошибка сохранения: ' + error.message, 'bad');
    } finally {
      ui.saveAnchors.disabled = false;
    }
  }

  function niceGridStep(span) {
    var raw = span / 8;
    var magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 0.001))));
    var normalized = raw / magnitude;
    if (normalized <= 1) {
      return magnitude;
    }
    if (normalized <= 2) {
      return 2 * magnitude;
    }
    if (normalized <= 5) {
      return 5 * magnitude;
    }
    return 10 * magnitude;
  }

  function resizeMapCanvas() {
    var rect = ui.map.getBoundingClientRect();
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    var pixelWidth = Math.max(1, Math.round(rect.width * ratio));
    var pixelHeight = Math.max(1, Math.round(rect.height * ratio));
    if (ui.map.width !== pixelWidth || ui.map.height !== pixelHeight) {
      ui.map.width = pixelWidth;
      ui.map.height = pixelHeight;
    }
    return { width: rect.width, height: rect.height, ratio: ratio };
  }

  function mapBounds() {
    var points = [];
    state.anchors.forEach(function (anchor) {
      points.push({ x: Number(anchor.pos[0]), y: Number(anchor.pos[1]) });
    });
    state.waypoints.forEach(function (waypoint) {
      points.push({ x: waypoint.x, y: waypoint.y });
    });
    if (state.position) {
      points.push({ x: state.position.x, y: state.position.y });
    }
    if (ui.showTrail.checked) {
      points = points.concat(state.trail);
    }
    if (!points.length) {
      points = [{ x: 0, y: 0 }, { x: 4, y: 4 }];
    }

    var minX = Math.min.apply(null, points.map(function (point) { return point.x; }));
    var maxX = Math.max.apply(null, points.map(function (point) { return point.x; }));
    var minY = Math.min.apply(null, points.map(function (point) { return point.y; }));
    var maxY = Math.max.apply(null, points.map(function (point) { return point.y; }));
    var centerX = (minX + maxX) / 2;
    var centerY = (minY + maxY) / 2;
    var spanX = Math.max(maxX - minX + 1.5, 4);
    var spanY = Math.max(maxY - minY + 1.5, 4);

    return {
      centerX: centerX,
      centerY: centerY,
      spanX: spanX,
      spanY: spanY
    };
  }

  function drawMap() {
    if (!ui.map) {
      return;
    }
    var size = resizeMapCanvas();
    var context = ui.map.getContext('2d');
    context.setTransform(size.ratio, 0, 0, size.ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    context.fillStyle = '#0a101a';
    context.fillRect(0, 0, size.width, size.height);

    var bounds = mapBounds();
    var padding = 42;
    var scale = Math.min(
      (size.width - padding * 2) / bounds.spanY,
      (size.height - padding * 2) / bounds.spanX
    );
    scale = Math.max(scale, 1);

    state.mapView = {
      width: size.width,
      height: size.height,
      scale: scale,
      centerX: bounds.centerX,
      centerY: bounds.centerY
    };

    function project(point) {
      return {
        x: size.width / 2 + (point.y - bounds.centerY) * scale,
        y: size.height / 2 - (point.x - bounds.centerX) * scale
      };
    }

    var visibleSpan = Math.max(bounds.spanX, bounds.spanY);
    var gridStep = niceGridStep(visibleSpan);
    var minGridX = bounds.centerX - bounds.spanX / 2;
    var maxGridX = bounds.centerX + bounds.spanX / 2;
    var minGridY = bounds.centerY - bounds.spanY / 2;
    var maxGridY = bounds.centerY + bounds.spanY / 2;

    context.lineWidth = 1;
    context.strokeStyle = '#1c293b';
    context.fillStyle = '#64728a';
    context.font = '10px system-ui, sans-serif';

    for (var gridY = Math.ceil(minGridY / gridStep) * gridStep; gridY <= maxGridY; gridY += gridStep) {
      var vertical = project({ x: bounds.centerX, y: gridY });
      context.beginPath();
      context.moveTo(vertical.x, 0);
      context.lineTo(vertical.x, size.height);
      context.stroke();
      context.fillText('Y ' + gridY.toFixed(1), vertical.x + 3, size.height - 8);
    }
    for (var gridX = Math.ceil(minGridX / gridStep) * gridStep; gridX <= maxGridX; gridX += gridStep) {
      var horizontal = project({ x: gridX, y: bounds.centerY });
      context.beginPath();
      context.moveTo(0, horizontal.y);
      context.lineTo(size.width, horizontal.y);
      context.stroke();
      context.fillText('X ' + gridX.toFixed(1), 5, horizontal.y - 4);
    }

    if (ui.showRanges.checked && state.position) {
      var tagOnMap = project(state.position);
      state.anchors.forEach(function (anchor) {
        var distance = finiteNumber(state.distances[anchor.id]);
        if (distance === null || distance <= 0) {
          return;
        }
        var anchorOnMap = project({ x: anchor.pos[0], y: anchor.pos[1] });
        context.save();
        context.setLineDash([5, 5]);
        context.strokeStyle = '#53617a';
        context.beginPath();
        context.moveTo(tagOnMap.x, tagOnMap.y);
        context.lineTo(anchorOnMap.x, anchorOnMap.y);
        context.stroke();
        context.restore();
        context.fillStyle = '#9aa7bd';
        context.fillText(
          distance.toFixed(2) + ' м',
          (tagOnMap.x + anchorOnMap.x) / 2 + 4,
          (tagOnMap.y + anchorOnMap.y) / 2 - 4
        );
      });
    }

    if (ui.showTrail.checked && state.trail.length > 1) {
      context.strokeStyle = 'rgba(55,220,122,.55)';
      context.lineWidth = 2;
      context.beginPath();
      state.trail.forEach(function (point, index) {
        var projected = project(point);
        if (index === 0) {
          context.moveTo(projected.x, projected.y);
        } else {
          context.lineTo(projected.x, projected.y);
        }
      });
      context.stroke();
    }

    if (state.waypoints.length) {
      context.strokeStyle = '#ffbd45';
      context.lineWidth = 2;
      context.beginPath();
      state.waypoints.forEach(function (waypoint, index) {
        var projected = project(waypoint);
        if (index === 0) {
          context.moveTo(projected.x, projected.y);
        } else {
          context.lineTo(projected.x, projected.y);
        }
      });
      context.stroke();

      state.waypoints.forEach(function (waypoint, index) {
        var projected = project(waypoint);
        context.fillStyle = '#ffbd45';
        context.beginPath();
        context.arc(projected.x, projected.y, 6, 0, Math.PI * 2);
        context.fill();
        context.fillStyle = '#ffe2a3';
        context.fillText('P' + (index + 1), projected.x + 8, projected.y - 7);
      });
    }

    state.anchors.forEach(function (anchor) {
      var projected = project({ x: anchor.pos[0], y: anchor.pos[1] });
      context.fillStyle = '#54a7ff';
      context.fillRect(projected.x - 6, projected.y - 6, 12, 12);
      context.fillStyle = '#a8d3ff';
      context.fillText('A' + anchor.id, projected.x + 9, projected.y - 8);
    });

    if (state.position) {
      var current = project(state.position);
      context.fillStyle = 'rgba(55,220,122,.18)';
      context.beginPath();
      context.arc(current.x, current.y, 15, 0, Math.PI * 2);
      context.fill();
      context.strokeStyle = '#37dc7a';
      context.lineWidth = 3;
      context.beginPath();
      context.arc(current.x, current.y, 7, 0, Math.PI * 2);
      context.stroke();
      context.fillStyle = '#a7f5c8';
      context.fillText('T' + state.activeTagId, current.x + 11, current.y - 10);
    }
  }

  function addWaypoint(x, y, z) {
    if (![x, y, z].every(Number.isFinite) || z < 0) {
      setPanelStatus(ui.missionStatus, 'Координаты должны быть числами, Z не может быть отрицательным.', 'bad');
      return;
    }
    state.waypoints.push({ x: x, y: y, z: z });
    state.routeRevision += 1;
    state.missionUploaded = false;
    renderWaypoints();
    setPanelStatus(ui.missionStatus, 'Точка P' + state.waypoints.length + ' добавлена.', null);
  }

  function addWaypointFromInputs() {
    var x = finiteNumber(ui.waypointX.value);
    var y = finiteNumber(ui.waypointY.value);
    var z = finiteNumber(ui.waypointZ.value);
    if (x === null || y === null || z === null) {
      setPanelStatus(ui.missionStatus, 'Заполните X, Y и Z числовыми значениями.', 'bad');
      return;
    }
    addWaypoint(x, y, z);
  }

  function renderWaypoints() {
    ui.waypointList.innerHTML = '';
    if (!state.waypoints.length) {
      var empty = document.createElement('div');
      empty.className = 'muted';
      empty.style.padding = '10px 2px';
      empty.textContent = 'Точек пока нет.';
      ui.waypointList.appendChild(empty);
      ui.routeStats.textContent = 'Маршрут пуст.';
      drawMap();
      updateControlAvailability();
      return;
    }

    state.waypoints.forEach(function (waypoint, index) {
      var item = document.createElement('div');
      item.className = 'waypoint';

      var label = document.createElement('b');
      label.textContent = 'P' + (index + 1);
      item.appendChild(label);

      var coords = document.createElement('span');
      coords.textContent =
        'X ' + waypoint.x.toFixed(2) +
        ' · Y ' + waypoint.y.toFixed(2) +
        ' · Z ' + waypoint.z.toFixed(2) + ' м';
      item.appendChild(coords);

      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'icon-button';
      remove.dataset.waypointIndex = String(index);
      remove.title = 'Удалить точку';
      remove.textContent = '×';
      item.appendChild(remove);
      ui.waypointList.appendChild(item);
    });

    var distance = 0;
    for (var index = 1; index < state.waypoints.length; index += 1) {
      var previous = state.waypoints[index - 1];
      var current = state.waypoints[index];
      distance += Math.hypot(
        current.x - previous.x,
        current.y - previous.y,
        current.z - previous.z
      );
    }
    ui.routeStats.textContent =
      state.waypoints.length + ' точек · длина ' + distance.toFixed(2) + ' м';
    drawMap();
    updateControlAvailability();
  }

  function updateControlAvailability() {
    var unavailable = !state.mavConnected || state.commandBusy;
    ui.arm.disabled = unavailable;
    ui.disarm.disabled = unavailable;
    ui.setMode.disabled = unavailable;
    ui.uploadMission.disabled = unavailable || !state.waypoints.length;
    ui.startMission.disabled = unavailable || !state.missionUploaded;
  }

  function mavStatusLabel(data) {
    var parts = ['MAVLink: подключён'];
    var telemetry = data.telemetry && typeof data.telemetry === 'object'
      ? data.telemetry
      : {};
    var systemId = data.system_id;
    if (systemId === undefined) {
      systemId = data.target_system;
    }
    if (systemId !== undefined && systemId !== null) {
      parts.push('SYS ' + systemId);
    }
    var mode = typeof data.mode === 'string' ? data.mode : telemetry.mode;
    var armed = typeof data.armed === 'boolean' ? data.armed : telemetry.armed;
    if (typeof mode === 'string' && mode) {
      parts.push(mode);
    }
    if (typeof armed === 'boolean') {
      parts.push(armed ? 'ARMED' : 'DISARMED');
    }
    return parts.join(' · ');
  }

  async function pollMavlinkStatus() {
    if (state.mavStatusPollBusy) {
      return;
    }
    state.mavStatusPollBusy = true;
    try {
      var data = await apiRequest('/api/mavlink/status', { cache: 'no-store' });
      state.mavStatusKnown = true;
      state.mavConnected = data.connected === true;
      // Server readiness may only invalidate local state.  It must not mark an
      // unknown route (after reload/edit) as uploaded; only uploadMission can
      // bind the currently displayed route revision to the FC mission.
      if (!state.mavConnected || data.mission_ready !== true) {
        state.missionUploaded = false;
      }
      ui.mavDot.classList.remove('wait');
      ui.mavDot.classList.toggle('ok', state.mavConnected);

      if (state.mavConnected) {
        ui.mavState.textContent = mavStatusLabel(data);
        var telemetry = data.telemetry && typeof data.telemetry === 'object'
          ? data.telemetry
          : {};
        var currentMode = typeof data.mode === 'string' ? data.mode : telemetry.mode;
        if (typeof currentMode === 'string' &&
            Array.from(ui.flightMode.options).some(function (option) { return option.value === currentMode; }) &&
            document.activeElement !== ui.flightMode) {
          ui.flightMode.value = currentMode;
        }
      } else if (data.configured === false) {
        ui.mavState.textContent = 'MAVLink: не настроен';
      } else {
        ui.mavState.textContent = 'MAVLink: нет heartbeat';
      }
    } catch (error) {
      state.mavStatusKnown = true;
      state.mavConnected = false;
      state.missionUploaded = false;
      ui.mavDot.classList.remove('ok', 'wait');
      ui.mavState.textContent = 'MAVLink: ' + error.message;
    } finally {
      state.mavStatusPollBusy = false;
      updateControlAvailability();
    }
  }

  async function executeCommand(path, body, confirmation, statusElement, successText) {
    if (!state.mavConnected) {
      setPanelStatus(statusElement, 'Команда заблокирована: MAVLink не подключён.', 'bad');
      return null;
    }
    if (confirmation && !window.confirm(confirmation)) {
      return null;
    }

    state.commandBusy = true;
    updateControlAvailability();
    setPanelStatus(statusElement, 'Передача команды…', 'warning');
    try {
      var data = await jsonPost(path, body);
      setPanelStatus(statusElement, responseMessage(data, successText), 'good');
      return data;
    } catch (error) {
      if (error.status === 503) {
        state.mavConnected = false;
      }
      setPanelStatus(statusElement, 'Ошибка: ' + error.message, 'bad');
      return null;
    } finally {
      state.commandBusy = false;
      updateControlAvailability();
      pollMavlinkStatus();
    }
  }

  async function uploadMission() {
    if (!state.waypoints.length) {
      setPanelStatus(ui.missionStatus, 'Добавьте хотя бы одну точку.', 'bad');
      return;
    }
    var uploadRevision = state.routeRevision;
    var uploadWaypoints = state.waypoints.map(function (waypoint) {
      return { x: waypoint.x, y: waypoint.y, z: waypoint.z };
    });
    var data = await executeCommand(
      '/upload_route',
      uploadWaypoints,
      'Загрузить ' + uploadWaypoints.length + ' точек в настоящий автопилот по MAVLink?',
      ui.missionStatus,
      'Миссия принята автопилотом.'
    );
    if (data && state.routeRevision === uploadRevision) {
      state.missionUploaded = true;
      updateControlAvailability();
    } else if (data) {
      state.missionUploaded = false;
      setPanelStatus(
        ui.missionStatus,
        'Автопилот принял предыдущую версию маршрута. Загрузите текущую версию заново.',
        'warning'
      );
    }
  }

  async function startMission() {
    await executeCommand(
      '/action/mission/start',
      undefined,
      'Отправить настоящему автопилоту команду MAV_CMD_MISSION_START?',
      ui.missionStatus,
      'Запуск миссии подтверждён автопилотом.'
    );
  }

  function startRecording() {
    state.recording = true;
    state.recordStartedAt = Date.now();
    state.recordRows = [];
    ui.recordNote.disabled = true;
    ui.record.textContent = '■ Остановить и скачать';
    ui.record.classList.add('danger');
    setPanelStatus(ui.recordStatus, 'Запись активной метки начата.', 'good');
  }

  function stopRecording() {
    state.recording = false;
    ui.recordNote.disabled = false;
    ui.record.textContent = '● Начать запись';
    ui.record.classList.remove('danger');

    if (!state.recordRows.length) {
      setPanelStatus(ui.recordStatus, 'За время записи не получено ни одного пакета активной метки.', 'bad');
      return;
    }

    var newline = String.fromCharCode(13, 10);
    var note = ui.recordNote.value.trim();
    note = note.split(String.fromCharCode(10)).join(' ');
    note = note.split(String.fromCharCode(13)).join(' ');
    var lines = [
      '# Заметка: ' + (note || 'без заметки'),
      '# Дата: ' + new Date().toLocaleString(),
      '# Координаты исходные, без искусственного смещения и без EMA',
      'Time_s,Tag_ID,X_m,Y_m,Z_m,UWB_Voltage_V'
    ];
    state.recordRows.forEach(function (row) {
      lines.push(row.join(','));
    });

    var blob = new Blob(
      [String.fromCharCode(0xfeff) + lines.join(newline) + newline],
      { type: 'text/csv;charset=utf-8' }
    );
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = 'blimp_uwb_' + Date.now() + '.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
    setPanelStatus(ui.recordStatus, 'Сохранено пакетов: ' + state.recordRows.length + '.', 'good');
  }

  function connectWebSocket() {
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(protocol + '//' + location.host + '/ws');
    state.ws = ws;
    ui.wsState.textContent = 'WebSocket: подключение…';

    ws.onopen = function () {
      state.wsConnected = true;
      state.wsOpenedAt = Date.now();
      ui.wsDot.classList.add('ok');
      ui.wsState.textContent = 'WebSocket подключён';
      updateRealtimeStatus();
    };
    ws.onmessage = function (event) {
      try {
        handleUwbFrame(JSON.parse(event.data));
      } catch (error) {
        console.warn('Пропущен некорректный кадр дашборда:', error);
      }
    };
    ws.onclose = function () {
      if (state.ws !== ws) {
        return;
      }
      state.wsConnected = false;
      ui.wsDot.classList.remove('ok');
      ui.wsState.textContent = 'WebSocket отключён';
      state.reconnectTimer = window.setTimeout(connectWebSocket, 1000);
      updateRealtimeStatus();
    };
    ws.onerror = function () {
      ws.close();
    };
  }

  ui.ema.addEventListener('input', function () {
    ui.emaValue.textContent = Number(ui.ema.value).toFixed(2);
  });
  ui.showTrail.addEventListener('change', drawMap);
  ui.showRanges.addEventListener('change', drawMap);
  ui.clearTrail.addEventListener('click', function () {
    state.trail = [];
    drawMap();
  });
  ui.reloadAnchors.addEventListener('click', loadAnchors);
  ui.saveAnchors.addEventListener('click', saveAnchors);

  ui.addWaypoint.addEventListener('click', addWaypointFromInputs);
  [ui.waypointX, ui.waypointY, ui.waypointZ].forEach(function (input) {
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        addWaypointFromInputs();
      }
    });
  });
  ui.waypointList.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-waypoint-index]');
    if (!button) {
      return;
    }
    state.waypoints.splice(Number(button.dataset.waypointIndex), 1);
    state.routeRevision += 1;
    state.missionUploaded = false;
    renderWaypoints();
    setPanelStatus(ui.missionStatus, 'Точка удалена; миссию нужно загрузить заново.', 'warning');
  });
  ui.clearWaypoints.addEventListener('click', function () {
    state.waypoints = [];
    state.routeRevision += 1;
    state.missionUploaded = false;
    renderWaypoints();
    setPanelStatus(ui.missionStatus, 'Маршрут очищен.', null);
  });
  ui.uploadMission.addEventListener('click', uploadMission);
  ui.startMission.addEventListener('click', startMission);

  ui.map.addEventListener('dblclick', function (event) {
    if (!state.mapView) {
      return;
    }
    var rect = ui.map.getBoundingClientRect();
    var mapX = event.clientX - rect.left;
    var mapY = event.clientY - rect.top;
    var x = state.mapView.centerX - (mapY - state.mapView.height / 2) / state.mapView.scale;
    var y = state.mapView.centerY + (mapX - state.mapView.width / 2) / state.mapView.scale;
    var z = finiteNumber(ui.waypointZ.value);
    addWaypoint(x, y, z === null ? 1.2 : z);
  });

  ui.arm.addEventListener('click', function () {
    executeCommand(
      '/action/arm',
      undefined,
      'Отправить ARM настоящему дирижаблю?',
      ui.commandStatus,
      'Команда ARM подтверждена автопилотом.'
    );
  });
  ui.disarm.addEventListener('click', function () {
    executeCommand(
      '/action/disarm',
      undefined,
      'Отправить DISARM настоящему дирижаблю?',
      ui.commandStatus,
      'Команда DISARM подтверждена автопилотом.'
    );
  });
  ui.setMode.addEventListener('click', function () {
    var mode = ui.flightMode.value;
    executeCommand(
      '/action/mode',
      { mode: mode },
      'Переключить настоящий автопилот в режим ' + mode + '?',
      ui.commandStatus,
      'Режим ' + mode + ' подтверждён автопилотом.'
    );
  });
  ui.record.addEventListener('click', function () {
    if (state.recording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  window.addEventListener('resize', drawMap);
  if (window.ResizeObserver) {
    new ResizeObserver(drawMap).observe(ui.map);
  }

  resetTrackedTag();
  renderWaypoints();
  connectWebSocket();
  loadDashboardConfig();
  loadAnchors();
  pollMavlinkStatus();
  window.setInterval(updateRealtimeStatus, 500);
  window.setInterval(pollMavlinkStatus, 2000);
})();
