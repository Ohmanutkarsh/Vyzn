import { initShell } from './components/shell.js';
import { renderCameraTile } from './components/camera-tile.js';
import { renderFlagRow } from './components/flag-row.js';
import { openClipDrawer, initClipDrawer } from './components/clip-drawer.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

let camerasList = [];
let activeCameraId = null;
let showWatchAreas = false;
let stalledTimer = null;
let lastFrameTime = Date.now();
let flagsData = [];

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  initShell({ activePage: 'overview' });
  initClipDrawer({ onClipUpdated: () => loadFlags() });

  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = 'Overview';

  await loadOverviewData();
  await loadFlags();
  initSSE();
  attachPlayerControls();

  // Tab visibility disconnect handler per Section 6.2 & Ground Rules
  document.addEventListener('visibilitychange', handleVisibilityChange);

  // Periodic snapshot refresh for non-active camera tiles in strip
  setInterval(refreshStripSnapshots, 15000);
});

async function loadOverviewData() {
  const emptyState = document.getElementById('overview-empty-state');
  const activeContent = document.getElementById('overview-active-content');

  try {
    const res = await fetch('/api/cameras');
    if (!res.ok) throw new Error('Failed to load cameras');
    camerasList = await res.json();

    if (!camerasList || camerasList.length === 0) {
      if (emptyState) emptyState.style.display = 'flex';
      if (activeContent) activeContent.style.display = 'none';
      return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (activeContent) activeContent.style.display = 'block';

    // Default to first online camera, or first camera
    const onlineCam = camerasList.find(c => c.status === 'online');
    activeCameraId = onlineCam ? (onlineCam.id || onlineCam.camera_id) : (camerasList[0].id || camerasList[0].camera_id);

    renderPicker();
    renderStrip();
    startLiveStream(activeCameraId);
  } catch (err) {
    if (emptyState) {
      emptyState.style.display = 'flex';
      emptyState.innerHTML = '<p class="empty-state-text">Failed to connect to VYZN edge server.</p>';
    }
  }
}

function renderPicker() {
  const container = document.getElementById('camera-picker-container');
  if (!container) return;

  if (camerasList.length <= 4) {
    container.innerHTML = `
      <div class="segmented-control" role="tablist">
        ${camerasList.map(c => {
          const cid = c.id || c.camera_id;
          const isSelected = cid === activeCameraId;
          return `
            <button type="button" class="segmented-option ${isSelected ? 'is-selected' : ''}" data-pick-cam="${escapeHtml(cid)}">
              ${escapeHtml(c.name)}
            </button>
          `;
        }).join('')}
      </div>
    `;

    container.querySelectorAll('[data-pick-cam]').forEach(btn => {
      btn.addEventListener('click', () => {
        const cid = btn.getAttribute('data-pick-cam');
        switchActiveCamera(cid);
      });
    });
  } else {
    container.innerHTML = `
      <select class="form-input" id="select-camera-picker" style="height: 34px; padding: 0 8px; font-size: 13px;">
        ${camerasList.map(c => {
          const cid = c.id || c.camera_id;
          return `<option value="${escapeHtml(cid)}" ${cid === activeCameraId ? 'selected' : ''}>${escapeHtml(c.name)}</option>`;
        }).join('')}
      </select>
    `;

    const select = document.getElementById('select-camera-picker');
    if (select) {
      select.addEventListener('change', (e) => {
        switchActiveCamera(e.target.value);
      });
    }
  }
}

function renderStrip() {
  const strip = document.getElementById('cameras-strip-list');
  if (!strip) return;

  strip.innerHTML = camerasList.map(c => {
    const cid = c.id || c.camera_id;
    return renderCameraTile({ camera: c, isSelected: cid === activeCameraId, showActions: false });
  }).join('');

  strip.querySelectorAll('.camera-tile').forEach(tile => {
    tile.addEventListener('click', () => {
      const cid = tile.getAttribute('data-camera-id');
      switchActiveCamera(cid);
    });
  });
}

function switchActiveCamera(cid) {
  if (cid === activeCameraId) return;
  activeCameraId = cid;
  renderPicker();
  renderStrip();
  startLiveStream(activeCameraId);
}

function startLiveStream(cid) {
  const cam = camerasList.find(c => (c.id || c.camera_id) === cid);
  if (!cam) return;

  const nameEl = document.getElementById('player-camera-name');
  if (nameEl) nameEl.textContent = cam.name;

  const streamImg = document.getElementById('live-stream-img');
  const connectingOverlay = document.getElementById('player-connecting-overlay');
  const offlineOverlay = document.getElementById('player-offline-overlay');
  const statusBadge = document.getElementById('player-status-badge');
  const pulseDot = document.getElementById('live-pulse-dot');

  // Clear previous state
  if (connectingOverlay) connectingOverlay.style.display = 'none';
  if (offlineOverlay) offlineOverlay.style.display = 'none';
  if (stalledTimer) clearTimeout(stalledTimer);

  if (cam.status !== 'online') {
    // Show Offline state per Section 6.2
    if (streamImg) streamImg.src = cam.snapshot_url || `/api/cameras/${cid}/snapshot.jpg`;
    if (offlineOverlay) {
      offlineOverlay.style.display = 'flex';
      const banner = document.getElementById('offline-banner-text');
      if (banner) banner.textContent = cam.offline_since ? `Offline since ${cam.offline_since}` : 'Offline';
    }
    if (statusBadge) statusBadge.textContent = 'Offline';
    if (pulseDot) pulseDot.style.display = 'none';
    return;
  }

  // Camera is marked online: show Connecting shimmer first
  if (connectingOverlay) connectingOverlay.style.display = 'flex';
  if (statusBadge) statusBadge.textContent = 'Connecting…';
  if (pulseDot) pulseDot.style.display = 'none';

  // Point to live MJPEG stream
  if (streamImg) {
    streamImg.src = `/api/cameras/${cid}/stream?t=${Date.now()}`;

    streamImg.onload = () => {
      if (connectingOverlay) connectingOverlay.style.display = 'none';
      if (offlineOverlay) offlineOverlay.style.display = 'none';
      if (statusBadge) statusBadge.textContent = 'Live';
      if (pulseDot) pulseDot.style.display = 'inline-block';
      lastFrameTime = Date.now();
      resetStalledWatchdog();
    };

    streamImg.onerror = () => {
      if (connectingOverlay) connectingOverlay.style.display = 'none';
      if (offlineOverlay) offlineOverlay.style.display = 'flex';
      if (statusBadge) statusBadge.textContent = 'Offline';
      if (pulseDot) pulseDot.style.display = 'none';
    };
  }
}

function resetStalledWatchdog() {
  if (stalledTimer) clearTimeout(stalledTimer);
  stalledTimer = setTimeout(() => {
    // No new frame for 5 seconds -> Stalled / Reconnecting
    const statusBadge = document.getElementById('player-status-badge');
    const pulseDot = document.getElementById('live-pulse-dot');
    if (statusBadge) statusBadge.textContent = 'Reconnecting…';
    if (pulseDot) pulseDot.style.display = 'none';
  }, 5000);
}

function handleVisibilityChange() {
  const streamImg = document.getElementById('live-stream-img');
  if (!streamImg) return;

  if (document.visibilityState === 'hidden') {
    // Drop stream immediately to save bandwidth & CPU
    streamImg.src = '';
  } else {
    // Tab active again: resume stream
    if (activeCameraId) startLiveStream(activeCameraId);
  }
}

function attachPlayerControls() {
  // Fullscreen toggle
  const btnFullscreen = document.getElementById('btn-fullscreen');
  const frame = document.getElementById('live-player-frame');
  if (btnFullscreen && frame) {
    btnFullscreen.addEventListener('click', () => {
      if (!document.fullscreenElement) {
        frame.requestFullscreen?.().catch(() => {});
      } else {
        document.exitFullscreen?.().catch(() => {});
      }
    });
  }

  // Save picture button
  const btnSavePic = document.getElementById('btn-save-picture');
  if (btnSavePic) {
    btnSavePic.addEventListener('click', () => {
      if (!activeCameraId) return;
      const link = document.createElement('a');
      link.href = `/api/cameras/${activeCameraId}/snapshot.jpg?download=1&t=${Date.now()}`;
      link.download = `snapshot_${activeCameraId}_${Date.now()}.jpg`;
      link.click();
    });
  }

  // Toggle Watch Areas
  const btnToggleAreas = document.getElementById('btn-toggle-areas');
  const areasSvg = document.getElementById('watch-areas-overlay');
  if (btnToggleAreas && areasSvg) {
    btnToggleAreas.addEventListener('click', () => {
      showWatchAreas = !showWatchAreas;
      btnToggleAreas.classList.toggle('is-active', showWatchAreas);
      areasSvg.style.display = showWatchAreas ? 'block' : 'none';
      if (showWatchAreas) renderWatchAreasOverlay();
    });
  }

  // Player Retry
  const btnRetry = document.getElementById('btn-player-retry');
  if (btnRetry) {
    btnRetry.addEventListener('click', () => {
      if (activeCameraId) startLiveStream(activeCameraId);
    });
  }

  // Why offline button
  const btnWhyOffline = document.getElementById('btn-player-why-offline');
  const modalTroubleshoot = document.getElementById('modal-troubleshooting');
  if (btnWhyOffline && modalTroubleshoot) {
    btnWhyOffline.addEventListener('click', () => {
      modalTroubleshoot.style.display = 'flex';
    });
  }

  const btnCloseTroubleshoot = document.getElementById('btn-close-troubleshooting');
  if (btnCloseTroubleshoot && modalTroubleshoot) {
    btnCloseTroubleshoot.addEventListener('click', () => {
      modalTroubleshoot.style.display = 'none';
    });
  }
}

function renderWatchAreasOverlay() {
  const areasSvg = document.getElementById('watch-areas-overlay');
  if (!areasSvg) return;

  // Draw simulated watch area outline in --action with dimmed outside scrim
  areasSvg.innerHTML = `
    <defs>
      <mask id="scrim-mask">
        <rect width="100%" height="100%" fill="white" />
        <path d="M120,60 L520,60 L520,320 L120,320 Z" fill="black" />
      </mask>
    </defs>
    <!-- Scrim layer outside watch area -->
    <rect width="100%" height="100%" fill="rgba(0,0,0,0.5)" mask="url(#scrim-mask)" />
    <!-- Watch area outline -->
    <path d="M120,60 L520,60 L520,320 L120,320 Z" fill="none" stroke="var(--action)" stroke-width="2" />
    <text x="126" y="80" fill="var(--action)" font-size="12" font-weight="600" font-family="var(--font-sans)">Shop floor</text>
  `;
}

function refreshStripSnapshots() {
  const images = document.querySelectorAll('#cameras-strip-list .camera-thumb-img');
  const now = Date.now();
  images.forEach(img => {
    const baseSrc = img.src.split('?')[0];
    img.src = `${baseSrc}?t=${now}`;
  });
}

/**
 * Loads unreviewed flags from /api/clips/flags and updates the Overview panel.
 */
async function loadFlags() {
  const container = document.getElementById('flags-list-container');
  const title = document.getElementById('flags-header-title');
  const expiryBanner = document.getElementById('flags-expiry-banner');
  const expiryText = document.getElementById('flags-expiry-text');
  const footerLink = document.getElementById('flags-see-all-link');

  if (!container) return;

  try {
    const res = await fetch('/api/clips/flags?limit=10', { credentials: 'include' });
    if (!res.ok) return;
    const data = await res.json();
    flagsData = data.flags || [];
    const totalWaiting = data.totalWaiting !== undefined ? data.totalWaiting : flagsData.length;
    const expiringSoon = data.expiringSoonCount || 0;

    if (title) title.textContent = `Flags · ${totalWaiting} waiting`;

    if (flagsData.length === 0) {
      container.innerHTML = `
        <div class="flags-empty-quiet">
          <div>${t('overview.flags_empty', 'Nothing needs your attention.')}</div>
        </div>
      `;
      if (expiryBanner) expiryBanner.style.display = 'none';
      if (footerLink) footerLink.textContent = t('overview.see_all_clips', 'See all in Clips');
      return;
    }

    // Max 5 desktop, max 3 mobile
    const maxShow = window.innerWidth < 1024 ? 3 : 5;
    const visibleFlags = flagsData.slice(0, maxShow);

    container.innerHTML = visibleFlags.map(clip => renderFlagRow({ clip })).join('');

    // Attach row open and dismiss handlers
    container.querySelectorAll('.flag-row').forEach(row => {
      const cid = row.getAttribute('data-clip-id');
      const clip = flagsData.find(c => c.id === cid);

      row.addEventListener('click', (e) => {
        // If clicking dismiss button
        if (e.target.closest('.btn-dismiss-flag')) {
          e.stopPropagation();
          const popover = document.getElementById('feedback-popover');
          if (popover && clip) {
            popover.style.display = 'flex';
            popover.setAttribute('data-target-clip-id', cid);
          }
          return;
        }
        // Clicking open or anywhere else
        if (clip) {
          openClipDrawer(clip, flagsData);
        }
      });
    });

    // 12-hour expiry warning banner per Section 6.2
    if (expiringSoon > 0 && expiryBanner && expiryText) {
      expiryBanner.style.display = 'flex';
      expiryText.textContent = `${expiringSoon} flags will be deleted in the next 12 hours. Download an evidence pack to keep a copy.`;
    } else if (expiryBanner) {
      expiryBanner.style.display = 'none';
    }

    // Footer link
    if (footerLink) {
      if (totalWaiting > visibleFlags.length) {
        footerLink.textContent = `See all ${totalWaiting} in Clips`;
      } else {
        footerLink.textContent = t('overview.see_all_clips', 'See all in Clips');
      }
    }
  } catch (e) {
    console.error('Error loading flags:', e);
  }
}

/**
 * Initializes SSE listener on /api/stream.
 */
function initSSE() {
  try {
    const es = new EventSource('/api/stream');
    es.addEventListener('flag.created', () => {
      loadFlags();
    });
    es.addEventListener('clip.updated', () => {
      loadFlags();
    });
  } catch (err) {
    // Fallback polling
    setInterval(loadFlags, 10000);
  }
}
