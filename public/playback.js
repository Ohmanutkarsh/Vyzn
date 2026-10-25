import { initShell } from './components/shell.js';
import { mountLiveCctvPlayer } from './components/live-player.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

let camerasList = [];
let activeCameraId = null;
let activeLivePlayer = null;
let edgeBaseUrl = null;
let edgeCameras = null;

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  await initShell({ activePage: 'playback' });
  await checkEdgeServer();
  await loadPlaybackData();

  // Snapshot refresh every 10 seconds
  setInterval(refreshCameraThumbnails, 10000);
});

async function checkEdgeServer() {
  const badge = document.getElementById('edge-badge');
  const badgeText = document.getElementById('edge-badge-text');
  const notice = document.getElementById('playback-notice');

  // If already on local server or localhost
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.port === '8000') {
    edgeBaseUrl = '';
    if (badge && badgeText) {
      badge.className = 'edge-badge is-connected';
      badgeText.textContent = 'Edge Node Connected';
    }
    if (notice) notice.style.display = 'none';
    return edgeBaseUrl;
  }

  // If on HTTPS (e.g. Vercel), browser blocks http://127.0.0.1:8000 media requests (Mixed Content)
  // Always use same-origin relative URLs on HTTPS so cloud streaming works 100% reliably.
  if (window.location.protocol === 'https:') {
    edgeBaseUrl = '';
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
        if (badge) {
          badge.className = 'edge-badge is-connected';
          badge.innerHTML = `<span class="edge-dot"></span><span>Local Edge Active · <a href="http://127.0.0.1:8000/playback" target="_blank" style="color: inherit; text-decoration: underline; font-weight: 600;">Open Direct Console</a></span>`;
        }
        if (notice) {
          notice.style.display = 'flex';
          notice.innerHTML = `<span style="font-size: 16px;">🟢</span><div>Local Edge Node is online on this machine. Playing cloud buffer. For direct 0ms local camera stream, <a href="http://127.0.0.1:8000/playback" target="_blank" style="color: var(--accent-primary, #3b82f6); font-weight: 600; text-decoration: underline;">Open Direct Edge Console (http://127.0.0.1:8000/playback)</a>.</div>`;
        }
        return edgeBaseUrl;
      }
    } catch (_) {}

    if (badge && badgeText) {
      badge.className = 'edge-badge is-cloud';
      badgeText.textContent = 'Cloud Mode';
    }
    if (notice) {
      notice.style.display = 'flex';
    }
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
      if (badge && badgeText) {
        badge.className = 'edge-badge is-connected';
        badgeText.textContent = 'Local Edge Connected (127.0.0.1:8000)';
      }
      if (notice) notice.style.display = 'none';

      try {
        const camRes = await fetch('http://127.0.0.1:8000/api/cameras', { mode: 'cors' });
        if (camRes.ok) edgeCameras = await camRes.json();
      } catch (e) {}

      return edgeBaseUrl;
    }
  } catch (e) {
    // Edge server not running locally
  }

  edgeBaseUrl = '';
  if (badge && badgeText) {
    badge.className = 'edge-badge is-cloud';
    badgeText.textContent = 'Cloud Mode';
  }
  if (notice) {
    notice.style.display = 'flex';
  }
  return edgeBaseUrl;
}

async function loadPlaybackData() {
  const emptyState = document.getElementById('playback-empty-state');
  const activeContent = document.getElementById('playback-active-content');

  try {
    const res = await fetch(`/api/cameras?t=${Date.now()}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Cache-Control': 'no-cache' }
    });

    if (res.ok) {
      camerasList = await res.json();
    }

    if ((!camerasList || camerasList.length === 0) && edgeCameras && Array.isArray(edgeCameras) && edgeCameras.length > 0) {
      camerasList = edgeCameras;
    } else if ((!camerasList || camerasList.length === 0) && edgeBaseUrl) {
      try {
        const edgeRes = await fetch(`${edgeBaseUrl}/api/cameras?t=${Date.now()}`, { mode: 'cors' });
        if (edgeRes.ok) {
          const eCams = await edgeRes.json();
          if (Array.isArray(eCams) && eCams.length > 0) camerasList = eCams;
        }
      } catch (e) {}
    }

    if (!camerasList || camerasList.length === 0) {
      if (emptyState) emptyState.style.display = 'flex';
      if (activeContent) activeContent.style.display = 'none';
      return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (activeContent) activeContent.style.display = 'block';

    // Parse URL parameter ?camera_id= or ?cam=
    const params = new URLSearchParams(window.location.search);
    const requestedId = params.get('camera_id') || params.get('cam');

    if (requestedId && camerasList.some(c => (c.id || c.camera_id) === requestedId)) {
      activeCameraId = requestedId;
    } else {
      activeCameraId = camerasList[0].id || camerasList[0].camera_id;
    }

    renderCamerasList();
    await mountPlaybackPlayer(activeCameraId);
  } catch (err) {
    console.error('Error loading playback data:', err);
    if (emptyState) emptyState.style.display = 'flex';
    if (activeContent) activeContent.style.display = 'none';
  }
}

async function mountPlaybackPlayer(cid) {
  const mountEl = document.getElementById('playback-player-mount');
  if (!mountEl) return;

  const cam = camerasList.find(c => (c.id || c.camera_id) === cid) || camerasList[0];
  const camName = cam ? cam.name : cid;

  if (activeLivePlayer) {
    activeLivePlayer.destroy();
    activeLivePlayer = null;
  }

  activeLivePlayer = await mountLiveCctvPlayer(mountEl, {
    cameraId: cid,
    cameraName: camName,
    cameras: camerasList,
    apiBaseUrl: edgeBaseUrl || '',
    isInline: true,
    onCameraChange: (newCid) => {
      switchActiveCamera(newCid);
    }
  });

  updateActiveCard(cid);
}

function switchActiveCamera(cid) {
  if (cid === activeCameraId) return;
  activeCameraId = cid;

  // Update URL without full page reload
  try {
    const url = new URL(window.location.href);
    url.searchParams.set('camera_id', cid);
    window.history.replaceState({}, '', url.toString());
  } catch (_) {}

  const cam = camerasList.find(c => (c.id || c.camera_id) === cid);
  const camName = cam ? cam.name : cid;

  if (activeLivePlayer) {
    activeLivePlayer.loadCamera(cid, camName);
  } else {
    mountPlaybackPlayer(cid);
  }

  updateActiveCard(cid);
}

function renderCamerasList() {
  const container = document.getElementById('playback-cameras-list');
  const countLabel = document.getElementById('playback-strip-count');
  if (!container) return;

  if (countLabel) {
    countLabel.textContent = `${camerasList.length} camera${camerasList.length === 1 ? '' : 's'}`;
  }

  container.innerHTML = camerasList.map(c => {
    const cid = c.id || c.camera_id;
    const cname = c.name || cid;
    const isActive = cid === activeCameraId;
    const statusText = c.is_online !== false ? 'Online' : 'Offline';
    const statusColor = c.is_online !== false ? '#34d399' : '#94a3b8';
    const thumbSrc = edgeBaseUrl ? `${edgeBaseUrl}/api/cameras/${cid}/snapshot.jpg?t=${Date.now()}` : `/api/cameras/${cid}/snapshot.jpg?t=${Date.now()}`;

    return `
      <div class="playback-cam-card ${isActive ? 'is-active' : ''}" data-camera-id="${escapeHtml(cid)}">
        <div class="playback-cam-thumb">
          <img src="${escapeHtml(thumbSrc)}" alt="${escapeHtml(cname)}" loading="lazy" onerror="this.src='/api/cameras/${escapeHtml(cid)}/mjpeg'" />
        </div>
        <div class="playback-cam-card-info">
          <span class="playback-cam-name" title="${escapeHtml(cname)}">${escapeHtml(cname)}</span>
          <span class="playback-cam-status" style="color: ${statusColor}">
            <span style="width: 6px; height: 6px; border-radius: 50%; background: ${statusColor}"></span>
            ${statusText}
          </span>
        </div>
      </div>
    `;
  }).join('');

  container.querySelectorAll('.playback-cam-card').forEach(card => {
    card.addEventListener('click', () => {
      const cid = card.getAttribute('data-camera-id');
      switchActiveCamera(cid);
    });
  });
}

function updateActiveCard(cid) {
  document.querySelectorAll('.playback-cam-card').forEach(card => {
    if (card.getAttribute('data-camera-id') === cid) {
      card.classList.add('is-active');
    } else {
      card.classList.remove('is-active');
    }
  });
}

function refreshCameraThumbnails() {
  const cards = document.querySelectorAll('.playback-cam-card img');
  const now = Date.now();
  cards.forEach(img => {
    const card = img.closest('.playback-cam-card');
    const cid = card ? card.getAttribute('data-camera-id') : null;
    if (cid) {
      img.src = edgeBaseUrl ? `${edgeBaseUrl}/api/cameras/${cid}/snapshot.jpg?t=${now}` : `/api/cameras/${cid}/snapshot.jpg?t=${now}`;
    }
  });
}
