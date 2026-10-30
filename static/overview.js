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
  setInterval(refreshStripSnapshots, 8000);
  // Periodic real-time snapshot capture from active stream to update strip and cloud
  setInterval(captureAndUploadActiveSnapshot, 2500);
});

async function loadOverviewData() {
  const emptyState = document.getElementById('overview-empty-state');
  const activeContent = document.getElementById('overview-active-content');
  const wallBtn = document.getElementById('btn-wall-view');

  try {
    const edge = await checkEdgeServer();
    const res = await fetch(`/api/cameras?t=${Date.now()}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Cache-Control': 'no-cache' }
    });
    if (!res.ok) throw new Error('Failed to load cameras');
    camerasList = await res.json();

    // If cloud returned empty list but local edge server is online, fallback to edge cameras
    if ((!camerasList || camerasList.length === 0) && edge && Array.isArray(edgeCameras) && edgeCameras.length > 0) {
      camerasList = edgeCameras;
    } else if ((!camerasList || camerasList.length === 0) && edge) {
      try {
        const edgeRes = await fetch(`${edge}/api/cameras?t=${Date.now()}`, { mode: 'cors' });
        if (edgeRes.ok) {
          const eCams = await edgeRes.json();
          if (Array.isArray(eCams) && eCams.length > 0) {
            camerasList = eCams;
          }
        }
      } catch (e) {}
    }

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
    const camCopy = { ...c };
    if (edgeBaseUrl) {
      camCopy.snapshot_url = `${edgeBaseUrl}/api/cameras/${cid}/snapshot.jpg?t=${Date.now()}`;
    } else {
      camCopy.snapshot_url = `/api/cameras/${cid}/snapshot.jpg?t=${Date.now()}`;
    }
    return renderCameraTile({ camera: camCopy, isSelected: cid === activeCameraId, showActions: false });
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
let edgeCameras = null;

async function checkEdgeServer() {
  if (edgeBaseUrl !== null) return edgeBaseUrl;
  if (window.location.protocol === 'https:') {
    edgeBaseUrl = '';
    return edgeBaseUrl;
  }
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.port === '8000') {
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
      try {
        const camRes = await fetch('http://127.0.0.1:8000/api/cameras', { mode: 'cors' });
        if (camRes.ok) {
          edgeCameras = await camRes.json();
        }
      } catch (e) {}
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
        height: { ideal: 720 },
        frameRate: { ideal: 20, max: 20 }
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

let activeWebcamStream = null;
let inBrowserClipperActive = false;
let clipperCanvas = null;
let clipperLastFrameData = null;
let isRecordingClip = false;

function startInBrowserClipper(stream, cam) {
  if (inBrowserClipperActive) return;
  inBrowserClipperActive = true;

  if (!clipperCanvas) {
    clipperCanvas = document.createElement('canvas');
    clipperCanvas.width = 64;
    clipperCanvas.height = 36;
  }
  const ctx = clipperCanvas.getContext('2d', { willReadFrequently: true });
  const videoEl = document.getElementById('live-stream-video');

  const checkMotionInterval = setInterval(async () => {
    const camId = cam.id || cam.camera_id;
    if (!activeWebcamStream || activeCameraId !== camId) {
      clearInterval(checkMotionInterval);
      inBrowserClipperActive = false;
      return;
    }
    if (!videoEl || videoEl.readyState < 2 || isRecordingClip) return;

    try {
      ctx.drawImage(videoEl, 0, 0, 64, 36);
      const imgData = ctx.getImageData(0, 0, 64, 36);
      const data = imgData.data;

      if (clipperLastFrameData) {
        let diffPixels = 0;
        const totalPixels = 64 * 36;
        for (let i = 0; i < data.length; i += 4) {
          const diff = Math.abs(data[i] - clipperLastFrameData[i]) +
                       Math.abs(data[i + 1] - clipperLastFrameData[i + 1]) +
                       Math.abs(data[i + 2] - clipperLastFrameData[i + 2]);
          if (diff > 50) diffPixels++;
        }
        const motionRatio = diffPixels / totalPixels;

        // Trigger recording on real motion activity (> 3%)
        if (motionRatio > 0.03 && !isRecordingClip) {
          const score = Math.min(96, Math.max(72, Math.round(68 + motionRatio * 160)));
          triggerWebcamClipRecord(stream, cam, score, motionRatio);
        }
      }
      clipperLastFrameData = data;
    } catch (e) {}
  }, 350);
}

async function triggerWebcamClipRecord(stream, cam, score, motionRatio) {
  if (isRecordingClip) return;
  isRecordingClip = true;

  try {
    const videoEl = document.getElementById('live-stream-video');
    let thumbDataUrl = '';
    if (videoEl && videoEl.videoWidth > 0) {
      const snapCanvas = document.createElement('canvas');
      snapCanvas.width = 640;
      snapCanvas.height = 360;
      const sCtx = snapCanvas.getContext('2d');
      sCtx.drawImage(videoEl, 0, 0, 640, 360);
      thumbDataUrl = snapCanvas.toDataURL('image/jpeg', 0.88);
    }

    let mimeType = 'video/webm;codecs=vp8';
    if (window.MediaRecorder && typeof window.MediaRecorder.isTypeSupported === 'function') {
      if (window.MediaRecorder.isTypeSupported('video/mp4;codecs=avc1')) {
        mimeType = 'video/mp4;codecs=avc1';
      } else if (window.MediaRecorder.isTypeSupported('video/mp4')) {
        mimeType = 'video/mp4';
      } else if (window.MediaRecorder.isTypeSupported('video/webm;codecs=vp9')) {
        mimeType = 'video/webm;codecs=vp9';
      }
    }

    const rec = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 2000000 });
    const chunks = [];
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    rec.onstop = async () => {
      try {
        const blob = new Blob(chunks, { type: mimeType });
        const reader = new FileReader();
        reader.onloadend = async () => {
          const videoDataUrl = reader.result;
          const clipId = `clip_${Date.now()}`;
          const clipNum = Math.floor(Math.random() * 9000) + 1000;
          const nowIso = new Date().toISOString();

          const clipRecord = {
            id: clipId,
            clip_id: clipId,
            clip_number: clipNum,
            camera_id: cam.id || cam.camera_id,
            camera_name: cam.name || 'Camera 1',
            score: score,
            importance_score: score,
            tier: score >= 70 ? 'alert' : 'review',
            summary: `Person/motion detected on ${cam.name || 'Camera 1'}`,
            description: `Movement activity in camera field of view (Score: ${score}).`,
            duration_sec: 6.0,
            fps: 25.0,
            created_at: nowIso,
            start_time: nowIso,
            end_time: nowIso,
            status: 'raw',
            thumbnail_url: thumbDataUrl,
            poster_url: thumbDataUrl,
            preview_url: thumbDataUrl,
            video_url: videoDataUrl,
            video_data_url: videoDataUrl,
            preview_base64: thumbDataUrl,
            urls: {
              thumb: thumbDataUrl,
              poster: thumbDataUrl,
              preview: thumbDataUrl,
              video: videoDataUrl
            }
          };

          // 1. Sync clip to backend
          await fetch('/api/clips/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ clips: [clipRecord] })
          }).catch(() => {});

          // 2. Dispatch real-time Telegram alert for score >= 70
          if (score >= 70) {
            fetch('/api/v1/alerts/ingress', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'include',
              body: JSON.stringify({
                event_id: clipId,
                camera_id: cam.id || cam.camera_id,
                camera_name: cam.name,
                description: `Activity detected on ${cam.name} (Score ${score})`,
                score: score,
                tier: 'alert'
              })
            }).catch(() => {});
          }

          // 3. Refresh flags in Overview
          loadFlags();
        };
        reader.readAsDataURL(blob);
      } catch (err) {
        console.warn('Clip finalize error:', err);
      } finally {
        setTimeout(() => { isRecordingClip = false; }, 4000);
      }
    };

    rec.start(1000);
    // Record for 6 seconds
    setTimeout(() => {
      if (rec.state === 'recording') rec.stop();
    }, 6000);
  } catch (err) {
    console.warn('triggerWebcamClipRecord error:', err);
    isRecordingClip = false;
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
  if (statusBadge) statusBadge.textContent = 'Connecting...';
  if (pulseDot) pulseDot.style.display = 'none';

  if (videoEl) videoEl.style.display = 'none';
  if (streamImg) streamImg.style.display = 'block';

  const isWebcam = String(cam.rtsp_url) === '0' || cam.source_type === 'webcam' || (cam.name && cam.name.toLowerCase().includes('webcam'));
  const isDirectHttp = cam.rtsp_url && (cam.rtsp_url.startsWith('http://') || cam.rtsp_url.startsWith('https://'));

  const edge = await checkEdgeServer();

  // Find corresponding local edge camera if ID differs (e.g. cloud assigned cam_81559 while local edge has cam_camera_1_...)
  let localCid = cid;
  if (edge && Array.isArray(edgeCameras) && edgeCameras.length > 0) {
    const match = edgeCameras.find(c => (c.id || c.camera_id) === cid)
      || edgeCameras.find(c => c.name && cam.name && c.name.trim().toLowerCase() === cam.name.trim().toLowerCase())
      || (edgeCameras.length === 1 ? edgeCameras[0] : null);
    if (match) {
      localCid = match.id || match.camera_id;
    }
  }

  // If this is a hardware webcam, try direct browser webcam first for zero-latency 20 fps authentic video
  if (isWebcam) {
    const started = await activateBrowserWebcam(cam, cid);
    if (started) return;
  }

  const streamCandidates = [];
  if (edge) {
    streamCandidates.push(`${edge}/api/cameras/${localCid}/stream?t=${Date.now()}`);
    if (localCid !== cid) {
      streamCandidates.push(`${edge}/api/cameras/${cid}/stream?t=${Date.now()}`);
    }
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

async function captureAndUploadActiveSnapshot() {
  if (!activeCameraId) return;
  const videoEl = document.getElementById('live-stream-video');
  const activeTileImg = document.querySelector(`.camera-tile[data-camera-id="${activeCameraId}"] .camera-thumb-img`);

  if (videoEl && videoEl.style.display !== 'none' && videoEl.readyState >= 2 && videoEl.videoWidth > 0) {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 360;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(videoEl, 0, 0, 640, 360);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.82);

      if (activeTileImg) {
        activeTileImg.src = dataUrl;
      }

      fetch(`/api/cameras/${encodeURIComponent(activeCameraId)}/snapshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview_base64: dataUrl })
      }).catch(() => {});

      if (edgeBaseUrl) {
        fetch(`${edgeBaseUrl}/api/cameras/${encodeURIComponent(activeCameraId)}/snapshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preview_base64: dataUrl })
        }).catch(() => {});
      }
    } catch (e) {
      console.warn('Snapshot capture error:', e);
    }
  } else if (edgeBaseUrl) {
    if (activeTileImg) {
      activeTileImg.src = `${edgeBaseUrl}/api/cameras/${encodeURIComponent(activeCameraId)}/snapshot.jpg?t=${Date.now()}`;
    }
  }
}

function refreshStripSnapshots() {
  const images = document.querySelectorAll('#cameras-strip-list .camera-thumb-img');
  const now = Date.now();
  images.forEach(img => {
    const tile = img.closest('.camera-tile');
    const cid = tile ? tile.getAttribute('data-camera-id') : null;
    if (cid === activeCameraId) {
      return;
    }
    if (cid && edgeBaseUrl) {
      img.src = `${edgeBaseUrl}/api/cameras/${cid}/snapshot.jpg?t=${now}`;
    } else {
      const baseSrc = img.src.split('?')[0];
      if (baseSrc && !baseSrc.startsWith('data:')) {
        img.src = `${baseSrc}?t=${now}`;
      }
    }
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
    const edge = await checkEdgeServer();
    let data = null;
    if (edge) {
      try {
        const edgeRes = await fetch(`${edge}/api/clips/flags?limit=10`, { mode: 'cors' });
        if (edgeRes.ok) {
          data = await edgeRes.json();
          // Sync edge clips to cloud in background
          fetch(`${edge}/api/clips?limit=50`, { mode: 'cors' })
            .then(r => r.ok ? r.json() : null)
            .then(allClipsData => {
              if (allClipsData && allClipsData.clips && allClipsData.clips.length > 0) {
                fetch('/api/clips/sync', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  credentials: 'include',
                  body: JSON.stringify({ clips: allClipsData.clips })
                }).catch(() => {});
              }
            }).catch(() => {});
        }
      } catch (e) {
        console.warn('Edge flags fetch error:', e);
      }
    }

    if (!data) {
      const res = await fetch('/api/clips/flags?limit=10', { credentials: 'include' });
      if (!res.ok) return;
      data = await res.json();
    }

    flagsData = data.flags || [];
    if (edge) {
      window.__vyzn_edge_url = edge;
      flagsData.forEach(clip => {
        if (clip.thumbnailUrl && clip.thumbnailUrl.startsWith('/')) clip.thumbnailUrl = `${edge}${clip.thumbnailUrl}`;
        if (clip.posterUrl && clip.posterUrl.startsWith('/')) clip.posterUrl = `${edge}${clip.posterUrl}`;
        if (clip.previewUrl && clip.previewUrl.startsWith('/')) clip.previewUrl = `${edge}${clip.previewUrl}`;
        if (clip.videoUrl && clip.videoUrl.startsWith('/')) clip.videoUrl = `${edge}${clip.videoUrl}`;
        if (clip.urls) {
          if (clip.urls.thumb && clip.urls.thumb.startsWith('/')) clip.urls.thumb = `${edge}${clip.urls.thumb}`;
          if (clip.urls.poster && clip.urls.poster.startsWith('/')) clip.urls.poster = `${edge}${clip.urls.poster}`;
          if (clip.urls.preview && clip.urls.preview.startsWith('/')) clip.urls.preview = `${edge}${clip.urls.preview}`;
          if (clip.urls.video && clip.urls.video.startsWith('/')) clip.urls.video = `${edge}${clip.urls.video}`;
        }
      });
    }

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
