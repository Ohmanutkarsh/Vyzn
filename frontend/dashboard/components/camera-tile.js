import { escapeHtml } from '../utils.js';

/**
 * Renders a CameraTile component for the Cameras list (S5) and live switcher (Overview).
 * Conforms to Section 6.5 and Section 6.2 specifications.
 * @param {object} props
 * @param {object} props.camera
 * @param {boolean} [props.isSelected=false]
 * @param {boolean} [props.showActions=false]
 * @returns {string} HTML string
 */
export function renderCameraTile({ camera, isSelected = false, showActions = false }) {
  const camId = camera.id || camera.camera_id;
  const thumbUrl = camera.snapshot_url || camera.snapshotUrl || `/api/cameras/${camId}/snapshot.jpg`;
  const isOnline = camera.status === 'online';
  const statusDotClass = isOnline ? 'neutral' : 'amber';
  const statusText = isOnline ? 'Online' : (camera.offline_since ? `Offline since ${camera.offline_since}` : 'Offline');

  let sourceLine = camera.source_line;
  if (!sourceLine) {
    if (camera.source_type === 'webcam') {
      sourceLine = 'Webcam';
    } else if (camera.source_type === 'phone') {
      sourceLine = `Phone camera · ${camera.ip_address || '192.168.1.15'}`;
    } else {
      sourceLine = `IP camera · ${camera.ip_address || '192.168.1.64'}`;
    }
  }

  const res = camera.resolution || { width: 1920, height: 1080 };
  const fps = camera.fps || 15.0;
  const facts = `${res.width}×${res.height} · ${fps} fps`;
  const areaCount = camera.area_count || 0;
  const areaSummary = areaCount > 0 ? `Watching ${areaCount} area${areaCount > 1 ? 's' : ''}` : 'Watching the whole view';

  return `
    <div class="camera-tile ${isSelected ? 'is-selected' : ''}" data-camera-id="${escapeHtml(camId)}" role="button" tabindex="0">
      <div class="camera-thumb-frame">
        <img class="camera-thumb-img" src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(camera.name)}" loading="lazy" onerror="this.onerror=null;this.src='/static/img/placeholder.jpg'" />
        ${!isOnline ? `
          <div class="camera-offline-overlay">
            <span class="offline-pill">${escapeHtml(statusText)}</span>
          </div>
        ` : ''}
      </div>
      <div class="camera-info-body">
        <div class="camera-title-row">
          <span class="camera-name">${escapeHtml(camera.name)}</span>
          ${showActions ? `
            <div class="camera-menu-wrap">
              <button type="button" class="btn-menu-trigger" data-cam-id="${escapeHtml(camId)}" aria-label="Camera options">⋯</button>
              <div class="camera-menu-dropdown" id="menu-${escapeHtml(camId)}" style="display: none;">
                <button type="button" class="menu-item action-rename" data-cam-id="${escapeHtml(camId)}" data-cam-name="${escapeHtml(camera.name)}">Rename</button>
                <a href="/areas/${escapeHtml(camId)}" class="menu-item action-areas">Choose watch areas</a>
                <button type="button" class="menu-item action-remove danger" data-cam-id="${escapeHtml(camId)}" data-cam-name="${escapeHtml(camera.name)}">Remove</button>
              </div>
            </div>
          ` : ''}
        </div>
        <div class="camera-status-line">
          <span class="status-dot ${statusDotClass}"></span>
          <span class="status-text">${escapeHtml(statusText)}</span>
        </div>
        <div class="camera-source-line">
          <span class="source-text mono-facts">${escapeHtml(sourceLine)}</span>
        </div>
        <div class="camera-facts-line">
          <span class="facts-text mono-facts">${escapeHtml(facts)}</span>
        </div>
        <div class="camera-area-summary">
          <span class="area-text">${escapeHtml(areaSummary)}</span>
          ${areaCount === 0 ? `<a href="/areas/${escapeHtml(camId)}" class="area-hint-link">Choose the area to watch</a>` : ''}
        </div>
      </div>
    </div>
  `.trim();
}
