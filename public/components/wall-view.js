/**
 * VYZN Wall View Component
 * End-to-end fullscreen CCTV grid view displaying all connected cameras.
 * Built with multiplexed WebSocket streaming to support 16+ cameras simultaneously
 * without hitting HTTP/1.1 per-origin socket limits.
 */

import { escapeHtml } from '../utils.js';

// Internal module state
let isWallOpen = false;
let allCameras = [];
let sortedCameras = [];
let currentPage = 0;
const TILES_PER_PAGE = 16;
let ws = null;
let wakeLock = null;
let idleTimer = null;
let rotationTimer = null;
let isRotationPaused = false;
let spotlightCameraId = null;
let activeMode = localStorage.getItem('vyzn_wall_mode') || 'all'; // 'all' | 'active'
let isAutoLocked = false;
let autoSpotlightTimer = null;
let cameraScoresHistory = {}; // { camId: { lastScore: 0, lastActiveTime: 0 } }
let lastFrameTimes = {}; // { camId: timestamp }
let offlineRetryCounters = {}; // { camId: { attempts: 0, nextRetryTime: 0 } }
let wallPollingTimer = null;

let didEnterNativeFullscreen = false;

/**
 * In simple terms: starts and opens the Wall View fullscreen grid.
 * Must be triggered by a direct user gesture (e.g. clicking the "Wall view" button).
 */
export async function openWallView(cameras = []) {
  if (isWallOpen) return;
  allCameras = Array.isArray(cameras) && cameras.length > 0 ? [...cameras] : [];
  
  // If cameras were not provided, fetch live from the server
  if (!allCameras || allCameras.length === 0) {
    try {
      const res = await fetch('/api/cameras', { credentials: 'include' });
      if (res.ok) {
        allCameras = await res.json();
      }
    } catch (e) {}
  }

  if (!allCameras || allCameras.length === 0) {
    console.warn('Wall view: No cameras connected to display.');
    return;
  }

  isWallOpen = true;
  didEnterNativeFullscreen = false;
  currentPage = 0;
  spotlightCameraId = null;
  cameraScoresHistory = {};
  lastFrameTimes = {};
  offlineRetryCounters = {};

  ensureContainerExists();
  const container = document.getElementById('wall-view-container');
  container.classList.add('is-active');

  // Request native browser fullscreen with fallback for iPhone Safari
  try {
    if (container.requestFullscreen) {
      await container.requestFullscreen();
      didEnterNativeFullscreen = true;
    } else if (container.webkitRequestFullscreen) {
      await container.webkitRequestFullscreen();
      didEnterNativeFullscreen = true;
    }
  } catch (err) {
    didEnterNativeFullscreen = false;
    // Fullscreen denied or unsupported; position:fixed inset:0 fallback takes over
    console.warn('Native fullscreen not permitted or fallback used:', err);
  }

  // Acquire Screen Wake Lock to keep the monitor on
  acquireWakeLock();

  // Attach event listeners for user controls, keyboard keys, and idle cursor timer
  attachWallEvents();

  // Render initial grid and start multiplexed stream
  updateSortedCameras();
  renderWallGrid();
  connectMultiplexedWebSocket();
  startWallSnapshotPolling();
  startRotationTimer();
  resetIdleTimer();
}

/**
 * In simple terms: closes Wall View, stops all streams, and restores the normal dashboard.
 */
export function closeWallView() {
  if (!isWallOpen) return;
  isWallOpen = false;
  didEnterNativeFullscreen = false;

  // Cleanly disconnect WebSocket and release video streams
  disconnectMultiplexedWebSocket();
  releaseWakeLock();

  // Stop timers
  if (wallPollingTimer) {
    clearInterval(wallPollingTimer);
    wallPollingTimer = null;
  }
  if (idleTimer) clearTimeout(idleTimer);
  if (rotationTimer) clearInterval(rotationTimer);
  if (autoSpotlightTimer) clearTimeout(autoSpotlightTimer);

  // If spotlight tile was open, clear its high-res source
  const spotlightImg = document.getElementById('spotlight-video-stream');
  if (spotlightImg) {
    spotlightImg.src = '';
  }

  const container = document.getElementById('wall-view-container');
  if (container) {
    container.classList.remove('is-active', 'is-idle');
    container.innerHTML = '';
  }

  // Exit native fullscreen if active
  try {
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen().catch(() => {});
      }
    }
  } catch (e) {}
}

/**
 * Creates the Wall View DOM shell if it does not already exist.
 */
function ensureContainerExists() {
  let container = document.getElementById('wall-view-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'wall-view-container';
    document.body.appendChild(container);
  }
}

/**
 * In simple terms: computes the camera ordering based on the selected mode:
 * - "All cameras": keeps the standard fixed camera order.
 * - "Active first": cameras with threat score >= 30 in the last 30s are placed first.
 */
function updateSortedCameras() {
  const now = Date.now();
  if (activeMode === 'active') {
    sortedCameras = [...allCameras].sort((a, b) => {
      const cidA = a.id || a.camera_id;
      const cidB = b.id || b.camera_id;
      const histA = cameraScoresHistory[cidA] || { lastScore: 0, lastActiveTime: 0 };
      const histB = cameraScoresHistory[cidB] || { lastScore: 0, lastActiveTime: 0 };

      const isAActive = (now - histA.lastActiveTime) < 30000 && histA.lastScore >= 30;
      const isBActive = (now - histB.lastActiveTime) < 30000 && histB.lastScore >= 30;

      if (isAActive && !isBActive) return -1;
      if (!isAActive && isBActive) return 1;
      return histB.lastScore - histA.lastScore;
    });
  } else {
    sortedCameras = [...allCameras];
  }
}

/**
 * Computes optimal columns and rows for end-to-end grid layout:
 * - 1 = 1x1
 * - 2 = 2x1 (landscape) / 1x2 (portrait)
 * - 3-4 = 2x2
 * - 5-6 = 3x2 (landscape) / 2x3 (portrait)
 * - 7-9 = 3x3
 * - 10-12 = 4x3 (landscape) / 3x4 (portrait)
 * - 13-16 = 4x4
 */
function calculateGridDimensions(count) {
  const isPortrait = window.innerHeight > window.innerWidth;

  if (count <= 1) return { cols: 1, rows: 1 };
  if (count === 2) return isPortrait ? { cols: 1, rows: 2 } : { cols: 2, rows: 1 };
  if (count <= 4) return { cols: 2, rows: 2 };
  if (count <= 6) return isPortrait ? { cols: 2, rows: 3 } : { cols: 3, rows: 2 };
  if (count <= 9) return { cols: 3, rows: 3 };
  if (count <= 12) return isPortrait ? { cols: 3, rows: 4 } : { cols: 4, rows: 3 };
  return { cols: 4, rows: 4 };
}

/**
 * Renders the top bar and camera grid tiles for the current page.
 */
function renderWallGrid() {
  const container = document.getElementById('wall-view-container');
  if (!container || !isWallOpen) return;

  const totalPages = Math.ceil(sortedCameras.length / TILES_PER_PAGE) || 1;
  if (currentPage >= totalPages) currentPage = 0;

  const startIndex = currentPage * TILES_PER_PAGE;
  const pageCameras = sortedCameras.slice(startIndex, startIndex + TILES_PER_PAGE);
  const { cols, rows } = calculateGridDimensions(pageCameras.length);

  container.innerHTML = `
    <!-- Top Bar Controls (Auto-hides on idle) -->
    <header class="wall-top-bar" id="wall-top-bar">
      <div class="wall-bar-left">
        <span class="wall-clock" id="wall-clock">--:--:--</span>
        <div class="wall-connection-status">
          <span class="wall-status-dot" id="wall-ws-dot"></span>
          <span id="wall-ws-label">Connected</span>
        </div>
      </div>

      <div class="wall-bar-center">
        <!-- Mode Switcher -->
        <div class="wall-mode-toggle" role="group" aria-label="Camera Display Mode">
          <button type="button" class="wall-mode-btn ${activeMode === 'all' ? 'is-active' : ''}" data-mode="all">All cameras</button>
          <button type="button" class="wall-mode-btn ${activeMode === 'active' ? 'is-active' : ''}" data-mode="active">Active first</button>
        </div>

        <!-- Lock Auto Changes Button -->
        <button type="button" class="wall-lock-btn ${isAutoLocked ? 'is-locked' : ''}" id="btn-wall-lock" title="Lock automatic grid reordering">
          <span>${isAutoLocked ? '🔒 Locked' : '🔓 Auto'}</span>
        </button>
      </div>

      <div class="wall-bar-right">
        <span class="wall-spotlight-indicator" id="wall-spotlight-tag">Spotlight (Esc to grid)</span>
        <button type="button" class="wall-exit-btn" id="btn-wall-exit" title="Exit Wall View (Esc)">
          <span>✕ Exit (Esc)</span>
        </button>
      </div>
    </header>

    <!-- Camera Grid Area (Fills 100% of screen with 2px gaps) -->
    <main class="wall-grid-area" id="wall-grid-area" style="grid-template-columns: repeat(${cols}, 1fr); grid-template-rows: repeat(${rows}, 1fr);">
      ${pageCameras.map((cam, idx) => {
        const cid = cam.id || cam.camera_id;
        let streamUrl = cam.stream_url || `/api/cameras/${encodeURIComponent(cid)}/stream`;
        let thumbUrl = cam.snapshot_url || cam.snapshotUrl || `/api/cameras/${encodeURIComponent(cid)}/snapshot.jpg`;
        if (typeof window !== 'undefined' && window.__vyzn_edge_url) {
          if (streamUrl.startsWith('/api/')) streamUrl = `${window.__vyzn_edge_url}${streamUrl}`;
          if (thumbUrl.startsWith('/api/')) thumbUrl = `${window.__vyzn_edge_url}${thumbUrl}`;
        }
        const keyNumber = idx + 1 <= 9 ? idx + 1 : null;
        const liveSrc = cam.status === 'online' ? streamUrl : thumbUrl;
        return `
          <div class="wall-tile border-neutral" id="tile-${escapeHtml(cid)}" data-cam-id="${escapeHtml(cid)}" data-key-num="${keyNumber || ''}">
            <img class="wall-tile-img" id="img-${escapeHtml(cid)}" src="${escapeHtml(liveSrc)}" alt="${escapeHtml(cam.name)}" onerror="this.dataset.streamFailed='true';if(this.src!=='${escapeHtml(thumbUrl)}'){this.src='${escapeHtml(thumbUrl)}';}" />
            
            <!-- Information Overlay (Auto-hides on idle) -->
            <div class="tile-overlay">
              <div class="tile-top-info">
                <div class="tile-camera-name-badge">
                  <span class="tile-dot ${cam.status === 'online' ? '' : 'offline'}" id="dot-${escapeHtml(cid)}"></span>
                  <span class="tile-cam-name" title="${escapeHtml(cam.name)}">${keyNumber ? keyNumber + '. ' : ''}${escapeHtml(cam.name)}</span>
                </div>
                <div class="tile-status-pill ${cam.is_recording ? 'rec' : 'live'}" id="pill-${escapeHtml(cid)}">
                  ${cam.is_recording ? 'REC' : 'LIVE'}
                </div>
              </div>
              <div class="tile-bottom-info">
                <span class="tile-score-tag" id="score-${escapeHtml(cid)}">Score: 0</span>
                <span class="tile-age-tag" id="age-${escapeHtml(cid)}">--</span>
              </div>
            </div>

            <!-- Stale Badge (Shown if no frame > 5s) -->
            <div class="tile-stale-banner" id="stale-${escapeHtml(cid)}">STALE</div>

            <!-- Offline Overlay with Retry In-Place -->
            <div class="tile-offline-overlay" id="offline-${escapeHtml(cid)}" style="${cam.status === 'offline' ? 'display: flex;' : 'display: none;'}">
              <div class="tile-offline-title">Camera Offline</div>
              <div class="tile-offline-msg" id="offline-msg-${escapeHtml(cid)}">Reconnecting in place…</div>
              <button type="button" class="tile-retry-btn" data-retry-cam="${escapeHtml(cid)}">Retry Now</button>
            </div>
          </div>
        `;
      }).join('')}
    </main>

    <!-- Page Indicator Dots (Rendered only when cameras > 16) -->
    ${totalPages > 1 ? `
      <div class="wall-page-dots" id="wall-page-dots">
        ${Array.from({ length: totalPages }, (_, i) => `
          <span class="wall-page-dot ${i === currentPage ? 'is-active' : ''}" data-page="${i}" title="Page ${i + 1}"></span>
        `).join('')}
        <span class="wall-rotation-status" id="wall-rotation-status">${isRotationPaused ? '(Paused)' : '15s'}</span>
      </div>
    ` : ''}
  `;

  // Update clock display immediately and keep it ticking
  updateClockDisplay();

  // Attach click-to-spotlight handlers to each tile
  container.querySelectorAll('.wall-tile').forEach(tile => {
    tile.addEventListener('click', (e) => {
      if (e.target.closest('.tile-retry-btn')) return;
      const cid = tile.getAttribute('data-cam-id');
      toggleSpotlight(cid);
    });
  });

  // Attach retry button handlers
  container.querySelectorAll('[data-retry-cam]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const cid = btn.getAttribute('data-retry-cam');
      retryCameraConnection(cid);
    });
  });

  // Attach mode switch buttons
  container.querySelectorAll('[data-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      const newMode = btn.getAttribute('data-mode');
      if (newMode !== activeMode) {
        activeMode = newMode;
        localStorage.setItem('vyzn_wall_mode', activeMode);
        updateSortedCameras();
        renderWallGrid();
        updateStreamSubscriptions();
      }
    });
  });

  // Attach lock button
  const lockBtn = document.getElementById('btn-wall-lock');
  if (lockBtn) {
    lockBtn.addEventListener('click', () => {
      isAutoLocked = !isAutoLocked;
      lockBtn.classList.toggle('is-locked', isAutoLocked);
      lockBtn.querySelector('span').textContent = isAutoLocked ? '🔒 Locked' : '🔓 Auto';
    });
  }

  // Attach exit button
  const exitBtn = document.getElementById('btn-wall-exit');
  if (exitBtn) {
    exitBtn.addEventListener('click', closeWallView);
  }

  // Attach page dot clicks
  container.querySelectorAll('[data-page]').forEach(dot => {
    dot.addEventListener('click', () => {
      currentPage = parseInt(dot.getAttribute('data-page'), 10) || 0;
      renderWallGrid();
      updateStreamSubscriptions();
    });
  });

  // Update active subscriptions on the multiplexed WebSocket
  updateStreamSubscriptions();
}

/**
 * Updates the digital clock in the top bar.
 */
function updateClockDisplay() {
  const clockEl = document.getElementById('wall-clock');
  if (clockEl) {
    const now = new Date();
    clockEl.textContent = now.toTimeString().split(' ')[0];
  }
}

/**
 * Connects to the single multiplexed WebSocket endpoint (/api/wall/stream).
 * Batches up to 16 camera frames over ONE connection, eliminating browser socket starvation.
 */
function connectMultiplexedWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/wall/stream`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      updateConnectionIndicator('online', 'Connected');
      updateStreamSubscriptions();
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'wall_batch' && payload.cameras) {
          handleIncomingBatch(payload.cameras);
        }
      } catch (err) {}
    };

    ws.onclose = () => {
      updateConnectionIndicator('reconnecting', 'Reconnecting…');
      if (isWallOpen) {
        setTimeout(connectMultiplexedWebSocket, 2000);
      }
    };

    ws.onerror = () => {
      updateConnectionIndicator('offline', 'Error');
    };
  } catch (err) {
    updateConnectionIndicator('offline', 'Disconnected');
  }
}

/**
 * Cleanly disconnects the multiplexed WebSocket.
 */
function disconnectMultiplexedWebSocket() {
  if (ws) {
    try {
      ws.send(JSON.stringify({ subscribe: [] }));
      ws.close();
    } catch (e) {}
    ws = null;
  }
}

/**
 * Polling fallback for live JPEG snapshots when WebSocket is reconnecting or on serverless hosting.
 */
function startWallSnapshotPolling() {
  if (wallPollingTimer) return;
  wallPollingTimer = setInterval(async () => {
    if (!isWallOpen) {
      clearInterval(wallPollingTimer);
      wallPollingTimer = null;
      return;
    }
    // Only poll snapshots if WebSocket is not actively streaming
    if (ws && ws.readyState === WebSocket.OPEN) return;

    const startIndex = currentPage * TILES_PER_PAGE;
    const pageCameras = sortedCameras.slice(startIndex, startIndex + TILES_PER_PAGE);
    for (const cam of pageCameras) {
      const cid = cam.id || cam.camera_id;
      const imgEl = document.getElementById(`img-${cid}`);
      if (imgEl && spotlightCameraId !== cid) {
        // Do NOT overwrite active live MJPEG stream on online cameras!
        if (cam.status === 'online' && imgEl.dataset.streamFailed !== 'true') {
          continue;
        }

        const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
        const baseUrl = isLocal ? '' : (window.__vyzn_edge_url || '');
        const snapUrl = `${baseUrl}/api/cameras/${encodeURIComponent(cid)}/snapshot.jpg?t=${Date.now()}`;

        const tempImg = new Image();
        tempImg.onload = () => {
          if (imgEl && isWallOpen) {
            imgEl.src = tempImg.src;
            const dotEl = document.getElementById(`dot-${cid}`);
            if (dotEl) dotEl.className = 'tile-dot';
            const staleEl = document.getElementById(`stale-${cid}`);
            if (staleEl) staleEl.style.display = 'none';
            const offlineEl = document.getElementById(`offline-${cid}`);
            if (offlineEl) offlineEl.style.display = 'none';
          }
        };
        tempImg.src = snapUrl;
      }
    }
  }, 2000);
}

/**
 * Updates the list of subscribed cameras on the active page.
 */
function updateStreamSubscriptions() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  const startIndex = currentPage * TILES_PER_PAGE;
  const pageCameras = sortedCameras.slice(startIndex, startIndex + TILES_PER_PAGE);
  const subscribedIds = pageCameras.map(c => c.id || c.camera_id);

  ws.send(JSON.stringify({
    subscribe: subscribedIds,
    fps: 5.0
  }));
}

/**
 * In simple terms: processes real-time frame batch from WebSocket.
 * Updates low-res image, threat score border color, REC status, and last-frame age.
 */
function handleIncomingBatch(cameraBatch) {
  const now = Date.now();
  let highestAlertCamera = null;

  for (const [camId, data] of Object.entries(cameraBatch)) {
    lastFrameTimes[camId] = now;

    // Track score history for "Active first" mode
    if (!cameraScoresHistory[camId]) {
      cameraScoresHistory[camId] = { lastScore: 0, lastActiveTime: 0 };
    }
    const score = typeof data.score === 'number' ? data.score : 0;
    cameraScoresHistory[camId].lastScore = score;
    if (score >= 30) {
      cameraScoresHistory[camId].lastActiveTime = now;
    }
    if (score >= 70) {
      highestAlertCamera = camId;
    }

    // Update tile image if not in spotlight mode
    if (spotlightCameraId !== camId) {
      const imgEl = document.getElementById(`img-${camId}`);
      if (imgEl && data.jpeg) {
        imgEl.src = `data:image/jpeg;base64,${data.jpeg}`;
      }
    }

    // Update border color based on real 3-second score:
    // neutral < 30, amber 30-70, red 70+ (subtle pulse)
    const tileEl = document.getElementById(`tile-${camId}`);
    if (tileEl) {
      tileEl.classList.remove('border-neutral', 'border-amber', 'border-red');
      if (score >= 70) {
        tileEl.classList.add('border-red');
      } else if (score >= 30) {
        tileEl.classList.add('border-amber');
      } else {
        tileEl.classList.add('border-neutral');
      }
    }

    // Update score tag
    const scoreEl = document.getElementById(`score-${camId}`);
    if (scoreEl) {
      scoreEl.textContent = `Score: ${score}`;
    }

    // Update recording badge
    const pillEl = document.getElementById(`pill-${camId}`);
    if (pillEl) {
      if (data.is_recording) {
        pillEl.className = 'tile-status-pill rec';
        pillEl.textContent = 'REC';
      } else {
        pillEl.className = 'tile-status-pill live';
        pillEl.textContent = 'LIVE';
      }
    }

    // Update connection status dot
    const dotEl = document.getElementById(`dot-${camId}`);
    if (dotEl) {
      dotEl.className = `tile-dot ${data.is_online ? '' : 'offline'}`;
    }

    // Hide stale and offline banners on active incoming frame
    const staleEl = document.getElementById(`stale-${camId}`);
    if (staleEl) staleEl.style.display = 'none';
    const offlineEl = document.getElementById(`offline-${camId}`);
    if (offlineEl && data.is_online) offlineEl.style.display = 'none';
  }

  // Handle "Active first" auto-spotlight for cameras hitting 70+
  if (activeMode === 'active' && !isAutoLocked && highestAlertCamera && spotlightCameraId !== highestAlertCamera) {
    toggleSpotlight(highestAlertCamera);

    // Auto-return to grid after 30 seconds of quiet
    if (autoSpotlightTimer) clearTimeout(autoSpotlightTimer);
    autoSpotlightTimer = setTimeout(() => {
      const hist = cameraScoresHistory[highestAlertCamera];
      if (!hist || hist.lastScore < 70) {
        if (spotlightCameraId === highestAlertCamera) {
          toggleSpotlight(null);
        }
      }
    }, 30000);
  }
}

/**
 * Updates top bar connection status dot and label.
 */
function updateConnectionIndicator(statusClass, label) {
  const dot = document.getElementById('wall-ws-dot');
  const txt = document.getElementById('wall-ws-label');
  if (dot) dot.className = `wall-status-dot ${statusClass}`;
  if (txt) txt.textContent = label;
}

/**
 * In simple terms: toggles Spotlight Mode for a specific camera tile.
 * Expands the camera to 100% fullscreen and switches it to the best high-res stream.
 * Clicking again or pressing Esc cancels spotlight and returns to the grid.
 */
function toggleSpotlight(cameraId) {
  const container = document.getElementById('wall-view-container');
  const spotlightTag = document.getElementById('wall-spotlight-tag');

  // If already spotlighted, return to grid view
  if (!cameraId || spotlightCameraId === cameraId) {
    if (spotlightCameraId) {
      const prevTile = document.getElementById(`tile-${spotlightCameraId}`);
      if (prevTile) {
        prevTile.classList.remove('is-spotlight');
        const img = prevTile.querySelector('.wall-tile-img');
        if (img) {
          const cam = allCameras.find(c => (c.id || c.camera_id) === spotlightCameraId);
          const isOnline = cam && cam.status === 'online';
          let streamUrl = (cam && cam.stream_url) || `/api/cameras/${encodeURIComponent(spotlightCameraId)}/stream`;
          let thumbUrl = (cam && (cam.snapshot_url || cam.snapshotUrl)) || `/api/cameras/${encodeURIComponent(spotlightCameraId)}/snapshot.jpg`;
          if (typeof window !== 'undefined' && window.__vyzn_edge_url) {
            if (streamUrl.startsWith('/api/')) streamUrl = `${window.__vyzn_edge_url}${streamUrl}`;
            if (thumbUrl.startsWith('/api/')) thumbUrl = `${window.__vyzn_edge_url}${thumbUrl}`;
          }
          img.src = isOnline ? streamUrl : thumbUrl;
        }
      }
    }
    spotlightCameraId = null;
    if (spotlightTag) spotlightTag.style.display = 'none';

    // Show all tiles again
    if (container) {
      container.querySelectorAll('.wall-tile').forEach(t => t.style.display = 'flex');
    }
    updateStreamSubscriptions();
    return;
  }

  // Focus the selected camera
  spotlightCameraId = cameraId;
  if (spotlightTag) {
    const cam = allCameras.find(c => (c.id || c.camera_id) === cameraId);
    spotlightTag.textContent = `Spotlight: ${cam ? cam.name : cameraId} (Esc to return)`;
    spotlightTag.style.display = 'inline-block';
  }

  // Hide other tiles and expand spotlight tile
  if (container) {
    container.querySelectorAll('.wall-tile').forEach(t => {
      const cid = t.getAttribute('data-cam-id');
      if (cid === cameraId) {
        t.style.display = 'flex';
        t.classList.add('is-spotlight');

        // Connect high-resolution MJPEG stream for spotlight tile only
        const img = t.querySelector('.wall-tile-img');
        if (img) {
          let sUrl = `/api/cameras/${encodeURIComponent(cameraId)}/stream?t=${Date.now()}`;
          if (typeof window !== 'undefined' && window.__vyzn_edge_url && sUrl.startsWith('/api/')) {
            sUrl = `${window.__vyzn_edge_url}${sUrl}`;
          }
          img.src = sUrl;
        }
      } else {
        t.style.display = 'none';
        t.classList.remove('is-spotlight');
      }
    });
  }
}

/**
 * Periodically checks for stale frames (>5s) and updates last-frame age labels.
 */
setInterval(() => {
  if (!isWallOpen) return;
  updateClockDisplay();
  const now = Date.now();

  const startIndex = currentPage * TILES_PER_PAGE;
  const pageCameras = sortedCameras.slice(startIndex, startIndex + TILES_PER_PAGE);

  pageCameras.forEach(cam => {
    const cid = cam.id || cam.camera_id;
    const lastTime = lastFrameTimes[cid];

    const ageEl = document.getElementById(`age-${cid}`);
    const staleEl = document.getElementById(`stale-${cid}`);

    if (lastTime) {
      const ageSec = ((now - lastTime) / 1000).toFixed(1);
      if (ageEl) ageEl.textContent = `${ageSec}s ago`;

      // Show STALE badge if no new frame arrives for > 5s
      if (ageSec > 5.0) {
        if (staleEl) staleEl.style.display = 'block';
        const dot = document.getElementById(`dot-${cid}`);
        if (dot) dot.className = 'tile-dot stale';
      } else {
        if (staleEl) staleEl.style.display = 'none';
      }
    } else {
      if (ageEl) ageEl.textContent = '--';
    }
  });
}, 1000);

/**
 * In-place camera retry with exponential backoff.
 */
function retryCameraConnection(cameraId) {
  if (!offlineRetryCounters[cameraId]) {
    offlineRetryCounters[cameraId] = { attempts: 0, nextRetryTime: 0 };
  }
  const info = offlineRetryCounters[cameraId];
  info.attempts += 1;
  const backoffSec = Math.min(60, Math.pow(2, info.attempts));

  const msgEl = document.getElementById(`offline-msg-${cameraId}`);
  if (msgEl) {
    msgEl.textContent = `Retrying in ${backoffSec}s (Attempt ${info.attempts})…`;
  }

  fetch(`/api/cameras/${encodeURIComponent(cameraId)}/snapshot`, { method: 'POST', credentials: 'include' })
    .then(res => res.json())
    .then(data => {
      if (data && data.snapshot_url) {
        const img = document.getElementById(`img-${cameraId}`);
        if (img) img.src = `${data.snapshot_url}&_r=${Date.now()}`;
      }
    })
    .catch(() => {});
}

/**
 * Auto-rotation for setups with > 16 cameras (rotates every 15s).
 */
function startRotationTimer() {
  if (rotationTimer) clearInterval(rotationTimer);
  rotationTimer = setInterval(() => {
    if (!isWallOpen || isRotationPaused) return;

    // Do not auto-rotate while any camera is alarming (score >= 70) or spotlight is active
    if (spotlightCameraId) return;
    const isAnyAlarming = Object.values(cameraScoresHistory).some(h => h.lastScore >= 70);
    if (isAnyAlarming) return;

    const totalPages = Math.ceil(sortedCameras.length / TILES_PER_PAGE);
    if (totalPages > 1) {
      currentPage = (currentPage + 1) % totalPages;
      renderWallGrid();
    }
  }, 15000);
}

/**
 * Auto-hides controls and cursor after 3 seconds of inactivity.
 */
function resetIdleTimer() {
  const container = document.getElementById('wall-view-container');
  if (!container) return;

  container.classList.remove('is-idle');
  if (idleTimer) clearTimeout(idleTimer);

  idleTimer = setTimeout(() => {
    if (isWallOpen) {
      container.classList.add('is-idle');
    }
  }, 3000);
}

/**
 * Attaches keyboard and mouse events to the Wall View container.
 */
function attachWallEvents() {
  const container = document.getElementById('wall-view-container');
  if (!container) return;

  // Reset idle timer on any mouse move or touch
  ['mousemove', 'mousedown', 'touchstart', 'keydown'].forEach(evt => {
    container.addEventListener(evt, resetIdleTimer, { passive: true });
  });

  // Pause auto-rotation on mouse hover / touch
  container.addEventListener('mouseenter', () => { isRotationPaused = true; updateRotationStatus(); });
  container.addEventListener('mouseleave', () => { isRotationPaused = false; updateRotationStatus(); });

  // Listen for fullscreen change events so Esc or app-switch exits cleanly
  document.addEventListener('fullscreenchange', handleFullscreenChange);
  document.addEventListener('webkitfullscreenchange', handleFullscreenChange);

  // Global keydown shortcuts
  window.addEventListener('keydown', handleKeyDown);

  // Handle tab visibility change
  document.addEventListener('visibilitychange', handleVisibilityChange);
}

function updateRotationStatus() {
  const statusEl = document.getElementById('wall-rotation-status');
  if (statusEl) {
    statusEl.textContent = isRotationPaused ? '(Paused)' : '15s';
  }
}

/**
 * Keydown handler for keyboard shortcuts:
 * - F: toggle Wall View fullscreen
 * - Esc: exit spotlight mode, or exit Wall View
 * - 1-9: spotlight camera 1 to 9
 * - Left/Right: page navigation
 * - Space: toggle pause rotation
 */
function handleKeyDown(e) {
  if (!isWallOpen) {
    if (e.key === 'f' || e.key === 'F') {
      const btn = document.getElementById('btn-wall-view');
      if (btn && !btn.disabled) {
        btn.click();
      }
    }
    return;
  }

  // F toggles fullscreen
  if (e.key === 'f' || e.key === 'F') {
    e.preventDefault();
    closeWallView();
    return;
  }

  // Esc returns from spotlight mode or closes Wall View
  if (e.key === 'Escape') {
    e.preventDefault();
    if (spotlightCameraId) {
      toggleSpotlight(null);
    } else {
      closeWallView();
    }
    return;
  }

  // Keys 1-9 spotlight the corresponding tile
  if (e.key >= '1' && e.key <= '9') {
    e.preventDefault();
    const index = parseInt(e.key, 10) - 1;
    const startIndex = currentPage * TILES_PER_PAGE;
    const targetCam = sortedCameras[startIndex + index];
    if (targetCam) {
      toggleSpotlight(targetCam.id || targetCam.camera_id);
    }
    return;
  }

  // Left/Right arrow keys change pages
  if (e.key === 'ArrowLeft') {
    e.preventDefault();
    const totalPages = Math.ceil(sortedCameras.length / TILES_PER_PAGE);
    if (totalPages > 1) {
      currentPage = (currentPage - 1 + totalPages) % totalPages;
      renderWallGrid();
    }
    return;
  }
  if (e.key === 'ArrowRight') {
    e.preventDefault();
    const totalPages = Math.ceil(sortedCameras.length / TILES_PER_PAGE);
    if (totalPages > 1) {
      currentPage = (currentPage + 1) % totalPages;
      renderWallGrid();
    }
    return;
  }

  // Space pauses / resumes auto-rotation
  if (e.key === ' ' || e.code === 'Space') {
    e.preventDefault();
    isRotationPaused = !isRotationPaused;
    updateRotationStatus();
  }
}

/**
 * Handles browser native fullscreen exit.
 */
function handleFullscreenChange() {
  if (isWallOpen && didEnterNativeFullscreen && !document.fullscreenElement && !document.webkitFullscreenElement) {
    // User exited native fullscreen via browser gesture
    closeWallView();
  }
}

/**
 * Tab visibility handler: pauses streams and releases wake lock when tab is hidden.
 */
function handleVisibilityChange() {
  if (!isWallOpen) return;
  if (document.visibilityState === 'hidden') {
    disconnectMultiplexedWebSocket();
    releaseWakeLock();
  } else if (document.visibilityState === 'visible') {
    acquireWakeLock();
    connectMultiplexedWebSocket();
  }
}

/**
 * Acquires Screen Wake Lock to keep the monitor awake during security monitoring.
 */
async function acquireWakeLock() {
  try {
    if ('wakeLock' in navigator) {
      wakeLock = await navigator.wakeLock.request('screen');
    }
  } catch (err) {}
}

/**
 * Releases Screen Wake Lock on exit.
 */
function releaseWakeLock() {
  if (wakeLock) {
    try {
      wakeLock.release();
    } catch (e) {}
    wakeLock = null;
  }
}
