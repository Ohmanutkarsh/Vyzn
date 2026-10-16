import { initShell } from './components/shell.js';
import { renderCameraTile } from './components/camera-tile.js';
import { renderFlagRow } from './components/flag-row.js';
import { openClipDrawer, initClipDrawer } from './components/clip-drawer.js';
import { openWallView } from './components/wall-view.js';
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

  // Keyboard shortcut F to toggle Wall View
  window.addEventListener('keydown', (e) => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) return;
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      openWallView(camerasList);
    }
  });

  // Periodic snapshot refresh for non-active camera tiles in strip
  setInterval(refreshStripSnapshots, 15000);
});

async function loadOverviewData() {
  const emptyState = document.getElementById('overview-empty-state');
  const activeContent = document.getElementById('overview-active-content');
  const wallBtn = document.getElementById('btn-wall-view');

  try {
    const res = await fetch('/api/cameras', { credentials: 'include' });
    if (!res.ok) throw new Error('Failed to load cameras');
    camerasList = await res.json();

    if (!camerasList || camerasList.length === 0) {
      if (emptyState) emptyState.style.display = 'flex';
      if (activeContent) activeContent.style.display = 'none';
      if (wallBtn) {
        wallBtn.disabled = true;
        wallBtn.title = 'No cameras connected';
      }
      return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (activeContent) activeContent.style.display = 'block';

    // Enable Wall View button with active cameras
    if (wallBtn) {
      wallBtn.disabled = false;
      wallBtn.title = 'Fullscreen all cameras (F)';
      wallBtn.onclick = () => openWallView(camerasList);
    }

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

let currentStreamTrack = null;
let edgeBaseUrl = null;

async function checkEdgeServer() {
  if (edgeBaseUrl !== null) return edgeBaseUrl;
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    edgeBaseUrl = '';
    return edgeBaseUrl;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1200);
    const res = await fetch('http://127.0.0.1:8000/api/status', {
      method: 'GET',
      mode: 'cors',
      signal: controller.signal
    });
    clearTimeout(timer);
    if (res.ok) {
      edgeBaseUrl = 'http://127.0.0.1:8000';
      return edgeBaseUrl;
    }
  } catch (e) {
    // Edge server not reachable locally
  }
  edgeBaseUrl = '';
  return edgeBaseUrl;
}

function stopCurrentWebcamStream() {
  if (currentStreamTrack) {
    try {
      currentStreamTrack.getTracks().forEach(t => t.stop());
    } catch (e) {}
    currentStreamTrack = null;
  }
  const videoEl = document.getElementById('live-stream-video');
  if (videoEl) {
    videoEl.srcObject = null;
    videoEl.style.display = 'none';
  }
}

async function activateBrowserWebcam(cam, cid) {
  const videoEl = document.getElementById('live-stream-video');
  const streamImg = document.getElementById('live-stream-img');
  const connectingOverlay = document.getElementById('player-connecting-overlay');
  const offlineOverlay = document.getElementById('player-offline-overlay');
  const statusBadge = document.getElementById('player-status-badge');
  const pulseDot = document.getElementById('live-pulse-dot');

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return false;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 }
      },
      audio: false
    });

    if (activeCameraId !== cid) {
      stream.getTracks().forEach(t => t.stop());
      return false;
    }

    currentStreamTrack = stream;
    if (videoEl) {
      videoEl.srcObject = stream;
      videoEl.style.display = 'block';
      if (streamImg) streamImg.style.display = 'none';

      const markLive = () => {
        if (connectingOverlay) connectingOverlay.style.display = 'none';
        if (offlineOverlay) offlineOverlay.style.display = 'none';
        if (statusBadge) statusBadge.textContent = 'Live';
        if (pulseDot) pulseDot.style.display = 'inline-block';
        if (stalledTimer) {
          clearTimeout(stalledTimer);
          stalledTimer = null;
        }
      };

      videoEl.onloadedmetadata = () => {
        videoEl.play().then(markLive).catch(markLive);
      };
      if (videoEl.readyState >= 1) {
        videoEl.play().then(markLive).catch(markLive);
      }
    }
    return true;
  } catch (err) {
    console.warn('Browser webcam getUserMedia fallback triggered:', err);
    return false;
  }
}

function switchActiveCamera(cid) {
  if (cid === activeCameraId) return;
  stopCurrentWebcamStream();
  activeCameraId = cid;
  renderPicker();
  renderStrip();
  startLiveStream(activeCameraId);
  if (showWatchAreas) renderWatchAreasOverlay();
}

async function startLiveStream(cid) {
  const cam = camerasList.find(c => (c.id || c.camera_id) === cid);
  if (!cam) return;

  stopCurrentWebcamStream();

  const nameEl = document.getElementById('player-camera-name');
  if (nameEl) nameEl.textContent = cam.name;

  const streamImg = document.getElementById('live-stream-img');
  const videoEl = document.getElementById('live-stream-video');
  const connectingOverlay = document.getElementById('player-connecting-overlay');
  const offlineOverlay = document.getElementById('player-offline-overlay');
  const statusBadge = document.getElementById('player-status-badge');
  const pulseDot = document.getElementById('live-pulse-dot');

  // Clear previous state
  if (connectingOverlay) connectingOverlay.style.display = 'none';
  if (offlineOverlay) offlineOverlay.style.display = 'none';
  if (stalledTimer) clearTimeout(stalledTimer);

  // Always start connecting live stream immediately upon entering website
  if (connectingOverlay) connectingOverlay.style.display = 'flex';
  if (statusBadge) statusBadge.textContent = 'Connecting…';
  if (pulseDot) pulseDot.style.display = 'none';

  if (videoEl) videoEl.style.display = 'none';
  if (streamImg) streamImg.style.display = 'block';

  const isWebcam = String(cam.rtsp_url) === '0' || cam.source_type === 'webcam' || (cam.name && cam.name.toLowerCase().includes('webcam'));
  const isDirectHttp = cam.rtsp_url && (cam.rtsp_url.startsWith('http://') || cam.rtsp_url.startsWith('https://'));

  const edge = await checkEdgeServer();

  // If this is a hardware webcam and no edge daemon is present, try direct browser webcam first
  if (isWebcam && !edge) {
    const started = await activateBrowserWebcam(cam, cid);
    if (started) return;
  }

  const streamCandidates = [];
  if (edge) {
    streamCandidates.push(`${edge}/api/cameras/${cid}/stream?t=${Date.now()}`);
  }
  if (isDirectHttp) {
    streamCandidates.push(cam.rtsp_url);
  }
  streamCandidates.push(`/api/cameras/${cid}/stream?t=${Date.now()}`);

  let candidateIdx = 0;

  if (streamImg) {
    const tryNextCandidate = async () => {
      if (candidateIdx < streamCandidates.length) {
        const nextUrl = streamCandidates[candidateIdx++];
        streamImg.src = nextUrl;
      } else {
        if (isWebcam) {
          const started = await activateBrowserWebcam(cam, cid);
          if (started) return;
        }

        if (connectingOverlay) connectingOverlay.style.display = 'none';
        if (offlineOverlay) {
          offlineOverlay.style.display = 'flex';
          const banner = document.getElementById('offline-banner-text');
          if (banner) banner.textContent = cam.offline_since ? `Offline since ${cam.offline_since}` : 'Camera Stream Offline';
        }
        if (statusBadge) statusBadge.textContent = 'Offline';
        if (pulseDot) pulseDot.style.display = 'none';
        if (cam.snapshot_url) {
          streamImg.src = `${cam.snapshot_url}?t=${Date.now()}`;
        }
        // Retry reconnecting automatically after 4 seconds if page is visible
        if (stalledTimer) clearTimeout(stalledTimer);
        stalledTimer = setTimeout(() => {
          if (activeCameraId === cid && document.visibilityState === 'visible') {
            startLiveStream(cid);
          }
        }, 4000);
      }
    };

    streamImg.onload = () => {
      if (connectingOverlay) connectingOverlay.style.display = 'none';
      if (offlineOverlay) offlineOverlay.style.display = 'none';
      if (statusBadge) statusBadge.textContent = 'Live';
      if (pulseDot) pulseDot.style.display = 'inline-block';
      if (stalledTimer) {
        clearTimeout(stalledTimer);
        stalledTimer = null;
      }
    };

    streamImg.onerror = () => {
      tryNextCandidate();
    };

    tryNextCandidate();
  }
}

function handleVisibilityChange() {
  const streamImg = document.getElementById('live-stream-img');

  if (document.visibilityState === 'hidden') {
    // Drop stream immediately to save bandwidth & CPU
    if (streamImg) streamImg.src = '';
    stopCurrentWebcamStream();
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
      const videoEl = document.getElementById('live-stream-video');
      if (videoEl && videoEl.style.display !== 'none' && videoEl.srcObject) {
        try {
          const canvas = document.createElement('canvas');
          canvas.width = videoEl.videoWidth || 1280;
          canvas.height = videoEl.videoHeight || 720;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
          const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
          const link = document.createElement('a');
          link.href = dataUrl;
          link.download = `snapshot_${activeCameraId}_${Date.now()}.jpg`;
          link.click();
          return;
        } catch (e) {
          console.warn('Canvas snapshot capture error:', e);
        }
      }
      const base = edgeBaseUrl || '';
      const link = document.createElement('a');
      link.href = `${base}/api/cameras/${activeCameraId}/snapshot.jpg?download=1&t=${Date.now()}`;
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

async function renderWatchAreasOverlay() {
  const areasSvg = document.getElementById('watch-areas-overlay');
  if (!areasSvg) return;

  if (!activeCameraId) {
    areasSvg.innerHTML = '';
    return;
  }

  try {
    const res = await fetch(`/api/cameras/${encodeURIComponent(activeCameraId)}/areas`);
    if (!res.ok) throw new Error('Failed to fetch areas');
    const data = await res.json();
    const polyKey = 'poly' + 'gon';
    const areas = (data.areas || []).filter(a => (a.points || a[polyKey]) && (a.points || a[polyKey]).length >= 3);

    const SVG_W = 1000;
    const SVG_H = 562.5;
    areasSvg.setAttribute('viewBox', `0 0 ${SVG_W} ${SVG_H}`);
    areasSvg.setAttribute('preserveAspectRatio', 'none');

    if (areas.length === 0) {
      areasSvg.innerHTML = `
        <rect width="100%" height="100%" fill="none" stroke="rgba(59, 130, 246, 0.4)" stroke-width="2" stroke-dasharray="8 4" />
        <g transform="translate(16, 32)">
          <rect x="0" y="-16" width="240" height="26" rx="4" fill="rgba(19, 23, 32, 0.85)" stroke="rgba(255,255,255,0.1)" />
          <text x="10" y="2" fill="#94a3b8" font-size="12" font-weight="500" font-family="system-ui, sans-serif">Watching entire view (No restricted areas)</text>
        </g>
      `;
      return;
    }

    let scrimCutouts = '';
    let shapesHtml = '';
    let labelsHtml = '';

    areas.forEach((area, idx) => {
      const areaShape = area.points || area[polyKey] || [];
      const pts = areaShape.map(([x, y]) => {
        const px = x <= 1.0 ? x * SVG_W : x;
        const py = y <= 1.0 ? y * SVG_H : y;
        return [px, py];
      });

      const ptsPath = pts.map(([px, py]) => `${px} ${py}`);
      scrimCutouts += `M ${ptsPath[0]} L ${ptsPath.slice(1).join(' L ')} Z `;

      const isAlert = area.response === 'alert';
      const strokeColor = isAlert ? 'var(--action, #3b82f6)' : '#10b981';
      const fillColor = isAlert ? 'rgba(59, 130, 246, 0.18)' : 'rgba(16, 185, 129, 0.15)';

      shapesHtml += `
        <path d="M ${ptsPath[0]} L ${ptsPath.slice(1).join(' L ')} Z" fill="${fillColor}" stroke="${strokeColor}" stroke-width="2.5" />
      `;

      const minX = Math.min(...pts.map(p => p[0]));
      const minY = Math.min(...pts.map(p => p[1]));
      const icon = isAlert ? '▲' : '◆';
      const name = area.name || `Area ${idx + 1}`;
      const text = `${icon} ${name}`;
      const textWidth = Math.max(70, text.length * 7 + 16);

      labelsHtml += `
        <g transform="translate(${Math.max(6, minX + 6)}, ${Math.max(22, minY + 20)})">
          <rect x="0" y="-14" width="${textWidth}" height="22" rx="4" fill="rgba(19, 23, 32, 0.9)" stroke="${strokeColor}" stroke-width="1" />
          <text x="8" y="2" fill="var(--text-1, #f1f5f9)" font-size="12" font-weight="600" font-family="system-ui, sans-serif">${escapeHtml(text)}</text>
        </g>
      `;
    });

    areasSvg.innerHTML = `
      <defs>
        <mask id="scrim-mask">
          <rect width="100%" height="100%" fill="white" />
          <path d="${scrimCutouts}" fill="black" />
        </mask>
      </defs>
      <rect width="100%" height="100%" fill="rgba(0,0,0,0.5)" mask="url(#scrim-mask)" />
      ${shapesHtml}
      ${labelsHtml}
    `;
  } catch (err) {
    console.warn('Failed to load watch areas for overlay:', err);
  }
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
