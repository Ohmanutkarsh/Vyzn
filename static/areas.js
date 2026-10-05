import { initShell } from './components/shell.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

// Global state
let currentCameraId = null;
let currentCamera = null;
let camerasList = [];
let watchAreas = [];
let selectedAreaIndex = null;
let activeTool = 'rect'; // 'rect' | 'shape'
let isDrawing = false;
let draftPoints = [];
let undoStack = [];
let isDirty = false;
let dragContext = null;
let pictureTimestamp = 'Now';

// SVG canvas dimensions (16:9 normalized coordinate space)
const SVG_W = 1000;
const SVG_H = 562.5;

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  initShell({ activePage: 'areas' });

  // Resolve camera ID from URL path or query parameter
  const pathParts = window.location.pathname.split('/').filter(Boolean);
  // /areas/:cameraId or /areas
  if (pathParts.length >= 2 && pathParts[0] === 'areas') {
    currentCameraId = pathParts[1];
  } else {
    const urlParams = new URLSearchParams(window.location.search);
    currentCameraId = urlParams.get('camera_id') || urlParams.get('id');
  }

  await routeView();

  window.addEventListener('beforeunload', (e) => {
    if (isDirty) {
      e.preventDefault();
      e.returnValue = t('areas.unsaved_warning', 'You have unsaved changes. Leave anyway?');
      return e.returnValue;
    }
  });
});

async function routeView() {
  const main = document.getElementById('main-content');
  try {
    const res = await fetch('/api/cameras');
    if (!res.ok) throw new Error('Failed to load cameras');
    camerasList = await res.json();

    if (!camerasList || camerasList.length === 0) {
      renderNoCameras(main);
      return;
    }

    // If specific camera is requested in URL, verify and load editor
    if (currentCameraId) {
      const match = camerasList.find(c => c.id === currentCameraId);
      if (match) {
        currentCamera = match;
        await renderEditor(main, currentCameraId);
        return;
      }
    }

    // If exactly 1 camera exists, per spec Section 6.4:
    // "One camera: skip the picker and go straight to its editor."
    if (camerasList.length === 1) {
      currentCameraId = camerasList[0].id;
      currentCamera = camerasList[0];
      // Update browser URL without reload
      window.history.replaceState({}, '', `/areas/${currentCameraId}`);
      await renderEditor(main, currentCameraId);
      return;
    }

    // Multiple cameras -> render picker
    renderPicker(main, camerasList);
  } catch (err) {
    main.innerHTML = `<div class="empty-state"><p class="empty-state-text">Failed to load cameras: ${escapeHtml(err.message)}</p></div>`;
  }
}

function renderNoCameras(container) {
  container.innerHTML = `
    <div class="empty-state" style="padding: var(--space-8) var(--space-4); text-align: center;">
      <div style="font-size: 36px; margin-bottom: var(--space-2);">📹</div>
      <h2 style="font-size: 18px; font-weight: 600; color: var(--text-1); margin: 0 0 6px 0;">${escapeHtml(t('overview.add_first_camera', 'Add your first camera'))}</h2>
      <p style="font-size: 14px; color: var(--text-2); margin: 0 0 var(--space-4) 0;">${escapeHtml(t('overview.add_first_camera_sub', 'Connect a CCTV camera, a recorder, or a spare phone.'))}</p>
      <a href="/cameras/new" class="btn btn-primary" style="text-decoration: none;">${escapeHtml(t('overview.add_camera_btn', 'Add a camera'))}</a>
    </div>
  `;
}

function renderPicker(container, cameras) {
  container.innerHTML = `
    <div class="areas-header-row">
      <div class="areas-title-group">
        <h1 id="txt-picker-title">${escapeHtml(t('areas.page_title', 'Watch areas'))}</h1>
        <p>${escapeHtml(t('areas.watching_whole_view', 'Watching the whole view. Draw an area to ignore everything else.'))}</p>
      </div>
    </div>
    <div class="areas-picker-grid" id="picker-grid">
      ${cameras.map(c => {
        const areaCount = c.area_count || (c.areas ? c.areas.length : 0);
        const areaSummary = areaCount === 0 
          ? t('cameras.watching_whole_view', 'Watching the whole view')
          : (areaCount === 1 
              ? t('cameras.watching_areas_count', 'Watching 1 area').replace('{count}', '1')
              : t('cameras.watching_areas_count_plural', `Watching ${areaCount} areas`).replace('{count}', areaCount));
        
        const ignoredCount = c.ignored_moments_count || 0;
        const ignoredLine = ignoredCount > 0 
          ? `<div class="picker-card-ignored-line">🛡️ ${escapeHtml(t('areas.ignored_moments_count', `Since you set this area, ${ignoredCount} moments outside it were ignored.`).replace('{count}', ignoredCount))}</div>`
          : '';

        const statusDot = c.status === 'online' 
          ? '<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--ok);"></span>' 
          : '<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--alert);"></span>';

        return `
          <div class="camera-tile" style="display:flex; flex-direction:column; justify-content:space-between;">
            <div>
              <div class="tile-thumbnail-frame" style="position:relative; width:100%; aspect-ratio:16/9; background:var(--video-bg); border-radius:var(--radius-interactive); overflow:hidden;">
                <img src="${c.snapshot_url || `/api/cameras/${c.id}/snapshot.jpg`}" alt="${escapeHtml(c.name)}" style="width:100%; height:100%; object-fit:cover;" onerror="this.src='/static/img/offline-placeholder.png';">
              </div>
              <div style="margin-top:12px;">
                <div style="display:flex; align-items:center; justify-content:space-between;">
                  <h3 style="font-size:15px; font-weight:600; color:var(--text-1); margin:0;">${escapeHtml(c.name)}</h3>
                  <div style="display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-2);">
                    ${statusDot} ${c.status === 'online' ? 'Online' : 'Offline'}
                  </div>
                </div>
                <div style="font-size:13px; color:var(--text-2); margin-top:4px;">${escapeHtml(areaSummary)}</div>
                ${ignoredLine}
              </div>
            </div>
            <div style="margin-top:16px;">
              <a href="/areas/${c.id}" class="btn btn-secondary" style="width:100%; text-decoration:none; text-align:center; box-sizing:border-box;">${escapeHtml(t('areas.edit_areas_btn', 'Edit areas'))}</a>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

async function renderEditor(container, cameraId) {
  try {
    const res = await fetch(`/api/cameras/${cameraId}/areas`);
    if (!res.ok) throw new Error('Failed to load watch areas for camera');
    const data = await res.json();
    currentCamera = data;
    watchAreas = (data.areas || []).map(a => ({
      ...a,
      polygon: a.polygon || []
    }));
    selectedAreaIndex = watchAreas.length > 0 ? 0 : null;
    undoStack = [];
    isDirty = false;

    // Time string for snapshot
    const now = new Date();
    pictureTimestamp = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

    buildEditorDom(container);
    attachCanvasInteractions();
    renderAll();
  } catch (err) {
    container.innerHTML = `<div class="empty-state"><p class="empty-state-text">Failed to load watch areas: ${escapeHtml(err.message)}</p></div>`;
  }
}

function buildEditorDom(container) {
  const camName = currentCamera ? currentCamera.camera_name : 'Camera';
  const ignoredCount = currentCamera ? (currentCamera.ignored_moments_count || 0) : 0;
  const ignoredBanner = ignoredCount > 0 
    ? `<div class="ignored-stats-banner">
         <span>🛡️</span>
         <span>${escapeHtml(t('areas.ignored_moments_count', `Since you set this area, ${ignoredCount} moments outside it were ignored.`).replace('{count}', ignoredCount))}</span>
       </div>`
    : '';

  const backLink = camerasList.length > 1 ? '<a href="/areas" class="btn btn-secondary" style="text-decoration:none; padding:6px 10px; font-size:12px;">‹ All cameras</a>' : '';

  container.innerHTML = `
    <div class="areas-header-row">
      <div class="areas-title-group" style="display:flex; align-items:center; gap:var(--space-3);">
        ${backLink}
        <div>
          <h1 id="txt-camera-name" style="margin:0;">${escapeHtml(camName)} · ${escapeHtml(t('areas.page_title', 'Watch areas'))}</h1>
          <p id="txt-areas-semantics">${escapeHtml(t('areas.watching_whole_view', 'Watching the whole view. Draw an area to ignore everything else.'))}</p>
        </div>
      </div>
      <div>
        <button type="button" class="btn btn-secondary" id="btn-update-picture">
          <span>🔄</span> <span id="btn-update-picture-txt">${escapeHtml(t('areas.update_picture', 'Update picture'))}</span>
        </button>
      </div>
    </div>

    ${ignoredBanner ? `<div style="margin-bottom:var(--space-4);">${ignoredBanner}</div>` : ''}

    <div class="areas-editor-layout">
      <!-- Left Column: Video Frame & SVG Overlay Canvas -->
      <div class="areas-canvas-column">
        <div class="areas-canvas-container" id="canvas-container">
          <img class="areas-canvas-img" id="canvas-img" src="/api/cameras/${currentCameraId}/snapshot.jpg?t=${Date.now()}" alt="${escapeHtml(camName)}">
          <svg class="areas-canvas-svg" id="canvas-svg" viewBox="0 0 ${SVG_W} ${SVG_H}" preserveAspectRatio="none">
            <!-- Scrim Fill (Even-Odd) -->
            <path class="scrim-fill" id="svg-scrim" d="M 0 0 H ${SVG_W} V ${SVG_H} H 0 Z"></path>
            <!-- Rendered Watch Areas -->
            <g id="svg-areas-group"></g>
            <!-- Interactive Handles for Selected Area -->
            <g id="svg-handles-group"></g>
            <!-- Active Draft Drawing Elements -->
            <g id="svg-draft-group"></g>
          </svg>
        </div>

        <div class="areas-canvas-footer">
          <div class="areas-tools-strip">
            <button type="button" class="tool-btn is-active" id="tool-rect">
              <span>⬛</span> ${escapeHtml(t('areas.rect_tool', 'Rectangle'))}
            </button>
            <button type="button" class="tool-btn" id="tool-shape">
              <span>⬠</span> ${escapeHtml(t('areas.shape_tool', 'Free shape'))}
            </button>
            <button type="button" class="tool-btn" id="btn-undo">
              <span>↩</span> ${escapeHtml(t('areas.undo', 'Undo'))}
            </button>
            <button type="button" class="tool-btn" id="btn-clear">
              <span>🗑️</span> ${escapeHtml(t('areas.clear', 'Clear'))}
            </button>
          </div>

          <div class="areas-legend-badge">
            <span class="legend-dot-bright"></span>
            <span style="color:var(--text-1); font-weight:500;">Bright: watched.</span>
            <span class="legend-dot-dimmed" style="margin-left:6px;"></span>
            <span style="color:var(--text-3);">Dimmed: ignored.</span>
          </div>
        </div>

        <div class="areas-meta-row">
          <span id="txt-picture-timestamp">Picture from ${escapeHtml(pictureTimestamp)}</span>
          <span style="font-size:11px; color:var(--text-3);">Tip: Drag corners to reshape, or edge midpoints to add points.</span>
        </div>
      </div>

      <!-- Right Column: Properties Sidebar / Mobile Bottom Sheet -->
      <aside class="areas-sidebar" id="areas-sidebar">
        <div>
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:var(--space-3);">
            <div class="sidebar-section-title" style="margin:0;" id="txt-areas-count-label">
              ${escapeHtml(t('areas.areas_on_this_camera', 'Areas on this camera'))} (<span id="count-areas">${watchAreas.length}</span>/5)
            </div>
            <button type="button" class="btn btn-secondary" id="btn-add-area" style="padding:4px 10px; font-size:12px;" ${watchAreas.length >= 5 ? 'disabled' : ''}>
              ${escapeHtml(t('areas.add_area', '+ Add area'))}
            </button>
          </div>
          <div class="areas-chip-list" id="areas-list">
            <!-- Rendered by renderAreasList() -->
          </div>
        </div>

        <!-- Selected Area Properties Form -->
        <div class="properties-form" id="properties-form" style="${selectedAreaIndex === null ? 'display:none;' : ''}">
          <div>
            <label class="form-group-label" for="input-area-name">${escapeHtml(t('areas.field_name', 'Name'))}</label>
            <input type="text" class="input" id="input-area-name" maxlength="32">
            <div class="name-suggestions">
              <button type="button" class="suggestion-chip" data-name="${escapeHtml(t('areas.suggest_counter', 'Cash counter'))}">${escapeHtml(t('areas.suggest_counter', 'Cash counter'))}</button>
              <button type="button" class="suggestion-chip" data-name="${escapeHtml(t('areas.suggest_floor', 'Shop floor'))}">${escapeHtml(t('areas.suggest_floor', 'Shop floor'))}</button>
              <button type="button" class="suggestion-chip" data-name="${escapeHtml(t('areas.suggest_door', 'Door'))}">${escapeHtml(t('areas.suggest_door', 'Door'))}</button>
              <button type="button" class="suggestion-chip" data-name="${escapeHtml(t('areas.suggest_godown', 'Godown'))}">${escapeHtml(t('areas.suggest_godown', 'Godown'))}</button>
            </div>
          </div>

          <div>
            <label class="form-group-label">${escapeHtml(t('areas.field_when_someone', 'When someone is here'))}</label>
            <div class="radio-group-cards">
              <label class="radio-choice-card is-active" id="label-resp-alert">
                <input type="radio" name="area-response" value="alert" style="display:none;" checked>
                <div class="radio-indicator"><div class="radio-dot"></div></div>
                <div>
                  <span style="font-weight:600;">▲ ${escapeHtml(t('areas.resp_alert', 'Send me an alert'))}</span>
                </div>
              </label>
              <label class="radio-choice-card" id="label-resp-review">
                <input type="radio" name="area-response" value="review" style="display:none;">
                <div class="radio-indicator"><div class="radio-dot"></div></div>
                <div>
                  <span style="font-weight:500;">◆ ${escapeHtml(t('areas.resp_review', 'Save a clip to review'))}</span>
                </div>
              </label>
            </div>
          </div>

          <div>
            <label class="form-group-label">${escapeHtml(t('areas.field_stay', 'Only flag if they stay'))}</label>
            <div class="segmented-group" id="dwell-segmented">
              <button type="button" class="segmented-btn is-active" data-dwell="0">${escapeHtml(t('areas.stay_immediate', 'Right away'))}</button>
              <button type="button" class="segmented-btn" data-dwell="10">${escapeHtml(t('areas.stay_10s', '10 s'))}</button>
              <button type="button" class="segmented-btn" data-dwell="30">${escapeHtml(t('areas.stay_30s', '30 s'))}</button>
              <button type="button" class="segmented-btn" data-dwell="60">${escapeHtml(t('areas.stay_60s', '60 s'))}</button>
            </div>
          </div>

          <div>
            <label class="form-group-label">${escapeHtml(t('areas.field_schedule', 'Watch this area'))}</label>
            <div class="segmented-group" id="schedule-segmented">
              <button type="button" class="segmented-btn is-active" data-schedule="always">${escapeHtml(t('areas.sched_always', 'All the time'))}</button>
              <button type="button" class="segmented-btn" data-schedule="outside_shop_hours">${escapeHtml(t('areas.sched_outside_hours', 'Outside shop hours'))}</button>
            </div>
          </div>

          <div class="save-actions-footer">
            <button type="button" class="btn btn-primary" id="btn-save-areas" style="width:100%; justify-content:center;">
              ${escapeHtml(t('areas.save_areas', 'Save areas'))}
            </button>
            <p class="applies-notice">
              ${escapeHtml(t('areas.applies_notice', 'Changes apply to new footage from the moment of saving. Clips already saved are not changed.'))}
            </p>
          </div>
        </div>

        <div id="no-selection-prompt" style="${selectedAreaIndex !== null ? 'display:none;' : ''} padding:var(--space-6) var(--space-2); text-align:center; color:var(--text-3); font-size:13px;">
          Draw an area on the picture, or choose one above to edit its settings.
        </div>
      </aside>
    </div>
  `;

  attachSidebarEventListeners();
}

function attachSidebarEventListeners() {
  // Tool toggle buttons
  const btnRect = document.getElementById('tool-rect');
  const btnShape = document.getElementById('tool-shape');
  if (btnRect && btnShape) {
    btnRect.onclick = () => {
      activeTool = 'rect';
      btnRect.classList.add('is-active');
      btnShape.classList.remove('is-active');
      cancelDraft();
    };
    btnShape.onclick = () => {
      activeTool = 'shape';
      btnShape.classList.add('is-active');
      btnRect.classList.remove('is-active');
      cancelDraft();
    };
  }

  // Undo button
  const btnUndo = document.getElementById('btn-undo');
  if (btnUndo) {
    btnUndo.onclick = handleUndo;
  }

  // Clear button
  const btnClear = document.getElementById('btn-clear');
  if (btnClear) {
    btnClear.onclick = () => {
      if (watchAreas.length === 0) return;
      if (confirm('Clear all watch areas for this camera?')) {
        pushUndo();
        watchAreas = [];
        selectedAreaIndex = null;
        isDirty = true;
        renderAll();
      }
    };
  }

  // Update Picture button
  const btnUpdatePic = document.getElementById('btn-update-picture');
  if (btnUpdatePic) {
    btnUpdatePic.onclick = async () => {
      const txt = document.getElementById('btn-update-picture-txt');
      if (txt) txt.textContent = t('areas.updating_picture', 'Updating picture…');
      btnUpdatePic.disabled = true;
      try {
        await fetch(`/api/cameras/${currentCameraId}/snapshot`, { method: 'POST' });
        const img = document.getElementById('canvas-img');
        if (img) img.src = `/api/cameras/${currentCameraId}/snapshot.jpg?t=${Date.now()}`;
        const now = new Date();
        pictureTimestamp = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        const stampEl = document.getElementById('txt-picture-timestamp');
        if (stampEl) stampEl.textContent = `Picture from ${pictureTimestamp}`;
        showToast('Picture updated.');
      } catch (err) {
        showToast('Failed to refresh picture: ' + err.message);
      } finally {
        if (txt) txt.textContent = t('areas.update_picture', 'Update picture');
        btnUpdatePic.disabled = false;
      }
    };
  }

  // Add area button
  const btnAddArea = document.getElementById('btn-add-area');
  if (btnAddArea) {
    btnAddArea.onclick = () => {
      if (watchAreas.length >= 5) return;
      // Generate default rectangle in center of frame
      pushUndo();
      const n = watchAreas.length + 1;
      const newArea = {
        id: `area_${currentCameraId}_${Date.now()}`,
        camera_id: currentCameraId,
        name: `Area ${n}`,
        polygon: [
          [0.2, 0.2],
          [0.8, 0.2],
          [0.8, 0.8],
          [0.2, 0.8]
        ],
        response: 'alert',
        min_stay_seconds: 0,
        schedule: 'always',
        version: 1
      };
      watchAreas.push(newArea);
      selectedAreaIndex = watchAreas.length - 1;
      isDirty = true;
      renderAll();
    };
  }

  // Name input
  const inputName = document.getElementById('input-area-name');
  if (inputName) {
    inputName.oninput = () => {
      if (selectedAreaIndex !== null && watchAreas[selectedAreaIndex]) {
        watchAreas[selectedAreaIndex].name = inputName.value.trim() || `Area ${selectedAreaIndex + 1}`;
        isDirty = true;
        renderAllAreasOnly();
      }
    };
  }

  // Name suggestion chips
  document.querySelectorAll('.suggestion-chip').forEach(chip => {
    chip.onclick = () => {
      if (selectedAreaIndex !== null && watchAreas[selectedAreaIndex]) {
        const val = chip.dataset.name;
        watchAreas[selectedAreaIndex].name = val;
        if (inputName) inputName.value = val;
        isDirty = true;
        renderAllAreasOnly();
      }
    };
  });

  // Response Radios
  const labelAlert = document.getElementById('label-resp-alert');
  const labelReview = document.getElementById('label-resp-review');
  if (labelAlert && labelReview) {
    labelAlert.onclick = () => {
      setAreaResponse('alert');
    };
    labelReview.onclick = () => {
      setAreaResponse('review');
    };
  }

  // Dwell segmented control
  document.querySelectorAll('#dwell-segmented .segmented-btn').forEach(btn => {
    btn.onclick = () => {
      const dwell = parseInt(btn.dataset.dwell, 10);
      setAreaDwell(dwell);
    };
  });

  // Schedule segmented control
  document.querySelectorAll('#schedule-segmented .segmented-btn').forEach(btn => {
    btn.onclick = () => {
      const sched = btn.dataset.schedule;
      setAreaSchedule(sched);
    };
  });

  // Save Areas Button
  const btnSave = document.getElementById('btn-save-areas');
  if (btnSave) {
    btnSave.onclick = saveWatchAreas;
  }
}

function setAreaResponse(resp) {
  if (selectedAreaIndex === null || !watchAreas[selectedAreaIndex]) return;
  pushUndo();
  watchAreas[selectedAreaIndex].response = resp;
  isDirty = true;

  const labelAlert = document.getElementById('label-resp-alert');
  const labelReview = document.getElementById('label-resp-review');
  if (labelAlert && labelReview) {
    if (resp === 'alert') {
      labelAlert.classList.add('is-active');
      labelReview.classList.remove('is-active');
    } else {
      labelReview.classList.add('is-active');
      labelAlert.classList.remove('is-active');
    }
  }
  renderAreasList();
  renderAllAreasOnly();
}

function setAreaDwell(dwell) {
  if (selectedAreaIndex === null || !watchAreas[selectedAreaIndex]) return;
  pushUndo();
  watchAreas[selectedAreaIndex].min_stay_seconds = dwell;
  isDirty = true;
  document.querySelectorAll('#dwell-segmented .segmented-btn').forEach(b => {
    b.classList.toggle('is-active', parseInt(b.dataset.dwell, 10) === dwell);
  });
}

function setAreaSchedule(sched) {
  if (selectedAreaIndex === null || !watchAreas[selectedAreaIndex]) return;
  pushUndo();
  watchAreas[selectedAreaIndex].schedule = sched;
  isDirty = true;
  document.querySelectorAll('#schedule-segmented .segmented-btn').forEach(b => {
    b.classList.toggle('is-active', b.dataset.schedule === sched);
  });
}

function pushUndo() {
  // Keep last 15 states
  undoStack.push(JSON.stringify(watchAreas));
  if (undoStack.length > 15) undoStack.shift();
}

function handleUndo() {
  if (undoStack.length === 0) return;
  const prev = undoStack.pop();
  try {
    watchAreas = JSON.parse(prev);
    if (selectedAreaIndex !== null && selectedAreaIndex >= watchAreas.length) {
      selectedAreaIndex = watchAreas.length > 0 ? watchAreas.length - 1 : null;
    }
    isDirty = true;
    renderAll();
  } catch (_) {}
}

function cancelDraft() {
  isDrawing = false;
  draftPoints = [];
  const draftG = document.getElementById('svg-draft-group');
  if (draftG) draftG.innerHTML = '';
}

// ---------------------------------------------------------------------------
// Canvas SVG Rendering & Interactions
// ---------------------------------------------------------------------------

function renderAll() {
  renderScrim();
  renderAreas();
  renderHandles();
  renderAreasList();
  updatePropertiesForm();
  updateSemanticsNotice();
}

function renderAllAreasOnly() {
  renderScrim();
  renderAreas();
  renderAreasList();
}

function updateSemanticsNotice() {
  const p = document.getElementById('txt-areas-semantics');
  if (!p) return;
  if (watchAreas.length === 0) {
    p.textContent = t('areas.watching_whole_view', 'Watching the whole view. Draw an area to ignore everything else.');
  } else if (watchAreas.length === 1) {
    p.textContent = t('areas.watching_areas_count', 'Watching 1 area. Everything else is ignored.');
  } else {
    p.textContent = t('areas.watching_areas_count_plural', `Watching ${watchAreas.length} areas. Everything else is ignored.`).replace('{count}', watchAreas.length);
  }
}

function renderScrim() {
  const scrim = document.getElementById('svg-scrim');
  if (!scrim) return;

  // Outer full frame rectangle (0 0 to W H)
  let d = `M 0 0 H ${SVG_W} V ${SVG_H} H 0 Z `;

  // Cutouts for every defined watch area
  watchAreas.forEach(area => {
    if (area.polygon && area.polygon.length >= 3) {
      const pts = area.polygon.map(([nx, ny]) => `${nx * SVG_W} ${ny * SVG_H}`);
      d += `M ${pts[0]} L ${pts.slice(1).join(' L ')} Z `;
    }
  });

  scrim.setAttribute('d', d);
}

function renderAreas() {
  const group = document.getElementById('svg-areas-group');
  if (!group) return;
  group.innerHTML = '';

  watchAreas.forEach((area, idx) => {
    if (!area.polygon || area.polygon.length < 3) return;
    const isSelected = idx === selectedAreaIndex;
    const ptsStr = area.polygon.map(([nx, ny]) => `${nx * SVG_W},${ny * SVG_H}`).join(' ');

    // Area polygon element
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', ptsStr);
    poly.setAttribute('class', `area-polygon ${isSelected ? 'is-active' : ''}`);
    poly.dataset.areaIdx = idx;

    // Click/Drag to select or translate shape
    poly.addEventListener('pointerdown', (e) => onShapePointerDown(e, idx));

    group.appendChild(poly);

    // Top-left label chip
    const [minX, minY] = getShapeTopLeft(area.polygon);
    const labelG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    labelG.setAttribute('class', 'area-label-group');
    labelG.setAttribute('transform', `translate(${minX * SVG_W + 6}, ${minY * SVG_H + 18})`);

    const icon = area.response === 'alert' ? '▲' : '◆';
    const textStr = `${icon} ${area.name}`;
    const textWidth = Math.max(70, textStr.length * 7 + 16);

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('class', 'area-label-rect');
    rect.setAttribute('x', '0');
    rect.setAttribute('y', '-12');
    rect.setAttribute('width', textWidth);
    rect.setAttribute('height', '20');

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('class', 'area-label-text');
    text.setAttribute('x', '8');
    text.setAttribute('y', '-1');
    text.textContent = textStr;

    labelG.appendChild(rect);
    labelG.appendChild(text);
    group.appendChild(labelG);
  });
}

function getShapeTopLeft(points) {
  let minX = 1.0;
  let minY = 1.0;
  for (const [x, y] of points) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
  }
  return [minX, minY];
}

function renderHandles() {
  const group = document.getElementById('svg-handles-group');
  if (!group) return;
  group.innerHTML = '';

  if (selectedAreaIndex === null || !watchAreas[selectedAreaIndex]) return;
  const area = watchAreas[selectedAreaIndex];
  if (!area.polygon || area.polygon.length < 3) return;

  // 1. Midpoint virtual insertion handles (ghost handles)
  for (let i = 0; i < area.polygon.length; i++) {
    const nextIdx = (i + 1) % area.polygon.length;
    const [p1x, p1y] = area.polygon[i];
    const [p2x, p2y] = area.polygon[nextIdx];
    const mx = ((p1x + p2x) / 2) * SVG_W;
    const my = ((p1y + p2y) / 2) * SVG_H;

    const midG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    midG.setAttribute('class', 'area-handle-midpoint-group');
    midG.dataset.insertAfter = i;

    const vis = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    vis.setAttribute('class', 'area-handle-midpoint-vis');
    vis.setAttribute('cx', mx);
    vis.setAttribute('cy', my);
    vis.setAttribute('r', '4');

    const touch = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    touch.setAttribute('class', 'area-handle-midpoint-touch');
    touch.setAttribute('cx', mx);
    touch.setAttribute('cy', my);
    touch.setAttribute('r', '16');

    touch.addEventListener('pointerdown', (e) => onMidpointPointerDown(e, selectedAreaIndex, i));

    midG.appendChild(vis);
    midG.appendChild(touch);
    group.appendChild(midG);
  }

  // 2. Point handles
  area.polygon.forEach(([nx, ny], ptIdx) => {
    const cx = nx * SVG_W;
    const cy = ny * SVG_H;

    const hG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    hG.setAttribute('class', 'area-handle-group');
    hG.setAttribute('tabindex', '0');
    hG.setAttribute('role', 'button');
    hG.setAttribute('aria-label', `Area point ${ptIdx + 1}`);

    const vis = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    vis.setAttribute('class', 'area-handle-vis');
    vis.setAttribute('cx', cx);
    vis.setAttribute('cy', cy);
    vis.setAttribute('r', '6');

    const touch = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    touch.setAttribute('class', 'area-handle-touch');
    touch.setAttribute('cx', cx);
    touch.setAttribute('cy', cy);
    touch.setAttribute('r', '22');

    // Pointer events for dragging
    touch.addEventListener('pointerdown', (e) => onPointPointerDown(e, selectedAreaIndex, ptIdx));

    // Keyboard navigation (WCAG nudge)
    hG.addEventListener('keydown', (e) => onPointKeyDown(e, selectedAreaIndex, ptIdx));

    hG.appendChild(vis);
    hG.appendChild(touch);
    group.appendChild(hG);
  });
}

function renderAreasList() {
  const listEl = document.getElementById('areas-list');
  const countSpan = document.getElementById('count-areas');
  const btnAdd = document.getElementById('btn-add-area');
  if (!listEl) return;

  if (countSpan) countSpan.textContent = watchAreas.length;
  if (btnAdd) btnAdd.disabled = watchAreas.length >= 5;

  if (watchAreas.length === 0) {
    listEl.innerHTML = `
      <div style="font-size:12px; color:var(--text-3); padding:8px 0; text-align:center;">
        No watch areas yet. VYZN is watching the whole view.
      </div>
    `;
    return;
  }

  listEl.innerHTML = watchAreas.map((area, idx) => {
    const isSelected = idx === selectedAreaIndex;
    const isAlert = area.response === 'alert';
    const tierIcon = isAlert ? '▲' : '◆';
    const tierClass = isAlert ? 'alert' : 'review';

    return `
      <div class="area-list-item ${isSelected ? 'is-selected' : ''}" data-idx="${idx}">
        <div class="area-item-info">
          <span class="area-tier-icon ${tierClass}">${tierIcon}</span>
          <span class="area-item-name">${escapeHtml(area.name)}</span>
        </div>
        <div class="area-item-actions">
          <button type="button" class="btn-icon-delete" data-del-idx="${idx}" aria-label="Delete area ${escapeHtml(area.name)}">✕</button>
        </div>
      </div>
    `;
  }).join('');

  // Attach selection & delete listeners
  listEl.querySelectorAll('.area-list-item').forEach(item => {
    item.onclick = (e) => {
      if (e.target.closest('.btn-icon-delete')) return;
      const idx = parseInt(item.dataset.idx, 10);
      selectArea(idx);
    };
  });

  listEl.querySelectorAll('.btn-icon-delete').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const idx = parseInt(btn.dataset.delIdx, 10);
      confirmDeleteArea(idx);
    };
  });
}

function selectArea(idx) {
  selectedAreaIndex = idx;
  renderHandles();
  renderAreas();
  renderAreasList();
  updatePropertiesForm();
}

function updatePropertiesForm() {
  const form = document.getElementById('properties-form');
  const prompt = document.getElementById('no-selection-prompt');
  if (!form || !prompt) return;

  if (selectedAreaIndex === null || !watchAreas[selectedAreaIndex]) {
    form.style.display = 'none';
    prompt.style.display = 'block';
    return;
  }

  form.style.display = 'flex';
  prompt.style.display = 'none';

  const area = watchAreas[selectedAreaIndex];

  // Name
  const inputName = document.getElementById('input-area-name');
  if (inputName) inputName.value = area.name || '';

  // Response Radios
  const labelAlert = document.getElementById('label-resp-alert');
  const labelReview = document.getElementById('label-resp-review');
  if (labelAlert && labelReview) {
    if (area.response === 'alert') {
      labelAlert.classList.add('is-active');
      labelReview.classList.remove('is-active');
    } else {
      labelReview.classList.add('is-active');
      labelAlert.classList.remove('is-active');
    }
  }

  // Dwell
  const dwell = area.min_stay_seconds || 0;
  document.querySelectorAll('#dwell-segmented .segmented-btn').forEach(b => {
    b.classList.toggle('is-active', parseInt(b.dataset.dwell, 10) === dwell);
  });

  // Schedule
  const sched = area.schedule || 'always';
  document.querySelectorAll('#schedule-segmented .segmented-btn').forEach(b => {
    b.classList.toggle('is-active', b.dataset.schedule === sched);
  });
}

function confirmDeleteArea(idx) {
  const area = watchAreas[idx];
  if (!area) return;
  const modal = document.getElementById('modal-delete-area');
  const title = document.getElementById('modal-del-title');
  const btnConfirm = document.getElementById('btn-confirm-del');
  const btnCancel = document.getElementById('btn-cancel-del');

  if (modal && title && btnConfirm && btnCancel) {
    title.textContent = `Delete ${area.name}?`;
    modal.style.display = 'flex';

    btnCancel.onclick = () => {
      modal.style.display = 'none';
    };

    btnConfirm.onclick = () => {
      pushUndo();
      watchAreas.splice(idx, 1);
      if (selectedAreaIndex === idx) {
        selectedAreaIndex = watchAreas.length > 0 ? 0 : null;
      } else if (selectedAreaIndex > idx) {
        selectedAreaIndex--;
      }
      isDirty = true;
      modal.style.display = 'none';
      renderAll();
    };
  } else {
    if (confirm(`Delete ${area.name}?`)) {
      pushUndo();
      watchAreas.splice(idx, 1);
      if (selectedAreaIndex === idx) {
        selectedAreaIndex = watchAreas.length > 0 ? 0 : null;
      } else if (selectedAreaIndex > idx) {
        selectedAreaIndex--;
      }
      isDirty = true;
      renderAll();
    }
  }
}

// ---------------------------------------------------------------------------
// Canvas Pointer & Keyboard Event Handling
// ---------------------------------------------------------------------------

function attachCanvasInteractions() {
  const svg = document.getElementById('canvas-svg');
  if (!svg) return;

  svg.addEventListener('pointerdown', onSvgPointerDown);
  window.addEventListener('pointermove', onWindowPointerMove);
  window.addEventListener('pointerup', onWindowPointerUp);
  window.addEventListener('keydown', onGlobalKeyDown);
}

function getSvgCoords(e) {
  const svg = document.getElementById('canvas-svg');
  if (!svg) return [0, 0, 0, 0];
  const pt = svg.createSVGPoint();
  pt.x = e.clientX;
  pt.y = e.clientY;
  const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
  const nx = Math.max(0, Math.min(1, svgP.x / SVG_W));
  const ny = Math.max(0, Math.min(1, svgP.y / SVG_H));
  return [svgP.x, svgP.y, nx, ny];
}

function onSvgPointerDown(e) {
  // If clicked directly on a handle or polygon, their handlers take precedence
  if (e.target.closest('.area-handle-touch') || e.target.closest('.area-handle-midpoint-touch') || e.target.closest('.area-polygon')) {
    return;
  }

  if (watchAreas.length >= 5) {
    showToast(t('areas.max_areas_notice', 'Maximum 5 areas per camera.'));
    return;
  }

  const [sx, sy, nx, ny] = getSvgCoords(e);

  if (activeTool === 'rect') {
    pushUndo();
    isDrawing = true;
    draftPoints = [[nx, ny], [nx, ny]];
    renderDraft();
  } else if (activeTool === 'shape') {
    if (!isDrawing) {
      pushUndo();
      isDrawing = true;
      draftPoints = [[nx, ny]];
    } else {
      // Check if clicked close to initial point to close shape
      const [initNx, initNy] = draftPoints[0];
      const dist = Math.hypot((nx - initNx) * SVG_W, (ny - initNy) * SVG_H);
      if (dist < 20 && draftPoints.length >= 3) {
        finishFreeShape();
        return;
      }
      draftPoints.push([nx, ny]);
    }
    renderDraft();
  }
}

function onWindowPointerMove(e) {
  if (dragContext) {
    onDragMove(e);
    return;
  }

  if (!isDrawing) return;
  const [sx, sy, nx, ny] = getSvgCoords(e);

  if (activeTool === 'rect' && draftPoints.length === 2) {
    draftPoints[1] = [nx, ny];
    renderDraft();
  } else if (activeTool === 'shape' && draftPoints.length > 0) {
    renderDraftWithRubberLine(nx, ny);
  }
}

function onWindowPointerUp(e) {
  if (dragContext) {
    dragContext = null;
    return;
  }

  if (isDrawing && activeTool === 'rect') {
    isDrawing = false;
    const [p0, p1] = draftPoints;
    const minX = Math.min(p0[0], p1[0]);
    const maxX = Math.max(p0[0], p1[0]);
    const minY = Math.min(p0[1], p1[1]);
    const maxY = Math.max(p0[1], p1[1]);

    // Minimum size threshold: 2% of frame
    if ((maxX - minX) > 0.02 && (maxY - minY) > 0.02) {
      const n = watchAreas.length + 1;
      const newArea = {
        id: `area_${currentCameraId}_${Date.now()}`,
        camera_id: currentCameraId,
        name: `Area ${n}`,
        polygon: [
          [minX, minY],
          [maxX, minY],
          [maxX, maxY],
          [minX, maxY]
        ],
        response: 'alert',
        min_stay_seconds: 0,
        schedule: 'always',
        version: 1
      };
      watchAreas.push(newArea);
      selectedAreaIndex = watchAreas.length - 1;
      isDirty = true;
    }
    cancelDraft();
    renderAll();
  }
}

function finishFreeShape() {
  if (draftPoints.length >= 3) {
    const n = watchAreas.length + 1;
    const newArea = {
      id: `area_${currentCameraId}_${Date.now()}`,
      camera_id: currentCameraId,
      name: `Area ${n}`,
      polygon: [...draftPoints],
      response: 'alert',
      min_stay_seconds: 0,
      schedule: 'always',
      version: 1
    };
    watchAreas.push(newArea);
    selectedAreaIndex = watchAreas.length - 1;
    isDirty = true;
  }
  cancelDraft();
  renderAll();
}

function renderDraft() {
  const group = document.getElementById('svg-draft-group');
  if (!group) return;
  group.innerHTML = '';

  if (activeTool === 'rect' && draftPoints.length === 2) {
    const [p0, p1] = draftPoints;
    const minX = Math.min(p0[0], p1[0]) * SVG_W;
    const maxX = Math.max(p0[0], p1[0]) * SVG_W;
    const minY = Math.min(p0[1], p1[1]) * SVG_H;
    const maxY = Math.max(p0[1], p1[1]) * SVG_H;

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', minX);
    rect.setAttribute('y', minY);
    rect.setAttribute('width', maxX - minX);
    rect.setAttribute('height', maxY - minY);
    rect.setAttribute('class', 'area-polygon draft-polygon');
    group.appendChild(rect);
  } else if (activeTool === 'shape' && draftPoints.length > 0) {
    const pts = draftPoints.map(([nx, ny]) => `${nx * SVG_W},${ny * SVG_H}`).join(' ');
    const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    polyline.setAttribute('points', pts);
    polyline.setAttribute('class', 'area-polygon draft-polygon');
    polyline.setAttribute('fill', 'none');
    group.appendChild(polyline);

    draftPoints.forEach(([nx, ny]) => {
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', nx * SVG_W);
      dot.setAttribute('cy', ny * SVG_H);
      dot.setAttribute('r', '5');
      dot.setAttribute('class', 'area-handle-vis');
      group.appendChild(dot);
    });
  }
}

function renderDraftWithRubberLine(cursorNx, cursorNy) {
  renderDraft();
  const group = document.getElementById('svg-draft-group');
  if (!group || draftPoints.length === 0) return;

  const [lastNx, lastNy] = draftPoints[draftPoints.length - 1];
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  line.setAttribute('x1', lastNx * SVG_W);
  line.setAttribute('y1', lastNy * SVG_H);
  line.setAttribute('x2', cursorNx * SVG_W);
  line.setAttribute('y2', cursorNy * SVG_H);
  line.setAttribute('class', 'area-rubber-line');
  group.appendChild(line);
}

// ---------------------------------------------------------------------------
// Dragging Manipulation: Point, Midpoint, Shape Interior
// ---------------------------------------------------------------------------

function onPointPointerDown(e, areaIdx, ptIdx) {
  e.stopPropagation();
  e.preventDefault();
  pushUndo();
  selectedAreaIndex = areaIdx;
  const [sx, sy, nx, ny] = getSvgCoords(e);
  dragContext = {
    type: 'point',
    areaIdx,
    ptIdx,
    startNx: nx,
    startNy: ny
  };
}

function onMidpointPointerDown(e, areaIdx, insertAfterIdx) {
  e.stopPropagation();
  e.preventDefault();
  pushUndo();
  selectedAreaIndex = areaIdx;
  const area = watchAreas[areaIdx];
  const nextIdx = (insertAfterIdx + 1) % area.polygon.length;
  const [p1x, p1y] = area.polygon[insertAfterIdx];
  const [p2x, p2y] = area.polygon[nextIdx];
  const midPoint = [(p1x + p2x) / 2, (p1y + p2y) / 2];

  // Insert new point into shape
  area.polygon.splice(insertAfterIdx + 1, 0, midPoint);
  isDirty = true;

  const newPtIdx = insertAfterIdx + 1;
  renderAll();

  // Immediately start dragging the newly created point
  const [sx, sy, nx, ny] = getSvgCoords(e);
  dragContext = {
    type: 'point',
    areaIdx,
    ptIdx: newPtIdx,
    startNx: nx,
    startNy: ny
  };
}

function onShapePointerDown(e, areaIdx) {
  e.stopPropagation();
  selectArea(areaIdx);
  pushUndo();
  const [sx, sy, nx, ny] = getSvgCoords(e);
  dragContext = {
    type: 'shape',
    areaIdx,
    startNx: nx,
    startNy: ny,
    origPoly: watchAreas[areaIdx].polygon.map(([x, y]) => [x, y])
  };
}

function onDragMove(e) {
  if (!dragContext) return;
  const [sx, sy, nx, ny] = getSvgCoords(e);

  if (dragContext.type === 'point') {
    const area = watchAreas[dragContext.areaIdx];
    if (!area) return;
    area.polygon[dragContext.ptIdx] = [nx, ny];
    isDirty = true;
    renderScrim();
    renderAreas();
    renderHandles();
  } else if (dragContext.type === 'shape') {
    const area = watchAreas[dragContext.areaIdx];
    if (!area) return;
    const dx = nx - dragContext.startNx;
    const dy = ny - dragContext.startNy;

    // Check bounds
    let canMove = true;
    for (const [ox, oy] of dragContext.origPoly) {
      if (ox + dx < 0 || ox + dx > 1 || oy + dy < 0 || oy + dy > 1) {
        canMove = false;
        break;
      }
    }

    if (canMove) {
      area.polygon = dragContext.origPoly.map(([ox, oy]) => [ox + dx, oy + dy]);
      isDirty = true;
      renderScrim();
      renderAreas();
      renderHandles();
    }
  }
}

function onPointKeyDown(e, areaIdx, ptIdx) {
  const area = watchAreas[areaIdx];
  if (!area) return;

  const step = e.shiftKey ? 0.05 : 0.01; // 5% or 1% per spec
  let handled = false;
  let [nx, ny] = area.polygon[ptIdx];

  if (e.key === 'ArrowLeft') {
    nx = Math.max(0, nx - step);
    handled = true;
  } else if (e.key === 'ArrowRight') {
    nx = Math.min(1, nx + step);
    handled = true;
  } else if (e.key === 'ArrowUp') {
    ny = Math.max(0, ny - step);
    handled = true;
  } else if (e.key === 'ArrowDown') {
    ny = Math.min(1, ny + step);
    handled = true;
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    if (area.polygon.length > 3) {
      pushUndo();
      area.polygon.splice(ptIdx, 1);
      isDirty = true;
      renderAll();
      handled = true;
    }
  }

  if (handled) {
    e.preventDefault();
    area.polygon[ptIdx] = [nx, ny];
    isDirty = true;
    renderScrim();
    renderAreas();
    renderHandles();
  }
}

function onGlobalKeyDown(e) {
  if (e.key === 'Escape') {
    cancelDraft();
  } else if (e.key === 'Enter' && isDrawing && activeTool === 'shape') {
    finishFreeShape();
  }
}

// ---------------------------------------------------------------------------
// Save Watch Areas to Backend
// ---------------------------------------------------------------------------

async function saveWatchAreas() {
  const btnSave = document.getElementById('btn-save-areas');
  if (btnSave) {
    btnSave.disabled = true;
    btnSave.textContent = 'Saving…';
  }

  try {
    const payload = {
      areas: watchAreas.map((a, idx) => ({
        id: a.id || `area_${currentCameraId}_${idx + 1}`,
        name: a.name || `Area ${idx + 1}`,
        polygon: a.polygon,
        response: a.response || 'alert',
        min_stay_seconds: a.min_stay_seconds || 0,
        schedule: a.schedule || 'always',
        version: a.version || 1
      }))
    };

    const res = await fetch(`/api/cameras/${currentCameraId}/areas`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to save areas');
    }

    const data = await res.json();
    watchAreas = data.areas || watchAreas;
    isDirty = false;

    showToast(t('areas.saved_toast', 'Areas saved. Applies to new footage.'));
    renderAll();
  } catch (err) {
    showToast(`Error: ${err.message}`);
  } finally {
    if (btnSave) {
      btnSave.disabled = false;
      btnSave.textContent = t('areas.save_areas', 'Save areas');
    }
  }
}

function showToast(msg) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.style.cssText = `
    background: var(--bg-surface);
    color: var(--text-1);
    border: 1px solid var(--action);
    border-radius: var(--radius-interactive);
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 500;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
    margin-top: 8px;
    pointer-events: auto;
    transition: all 180ms ease;
  `;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

// Window scope exports for automation tests
window.setAreaResponse = setAreaResponse;
window.setAreaDwell = setAreaDwell;
window.setAreaSchedule = setAreaSchedule;
window.saveWatchAreas = saveWatchAreas;
window.getWatchAreas = () => watchAreas;
