/**
 * VYZN Live CCTV Player with Timeshift & Rewind
 * Implements rolling fMP4 disk buffer playback via HLS.js.
 * Export: mountLiveCctvPlayer(container, options)
 */

const MODE_LIVE = 'live';
const MODE_PLAYBACK = 'playback';

/**
 * Ensures Hls.js is loaded in the browser document.
 */
function ensureHlsScript() {
  return new Promise((resolve, reject) => {
    if (window.Hls) {
      return resolve(window.Hls);
    }
    const existing = document.querySelector('script[data-hls-loader]');
    if (existing) {
      existing.addEventListener('load', () => resolve(window.Hls));
      existing.addEventListener('error', () => reject(new Error('HLS script load failed')));
      return;
    }

    const script = document.createElement('script');
    script.setAttribute('data-hls-loader', 'true');
    // Try local /static/hls.min.js first, fall back to CDN if local fails
    script.src = '/static/hls.min.js';
    script.onload = () => {
      if (window.Hls) resolve(window.Hls);
      else reject(new Error('Hls not on window after load'));
    };
    script.onerror = () => {
      // Fallback to CDN
      const fallbackScript = document.createElement('script');
      fallbackScript.src = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.8/dist/hls.min.js';
      fallbackScript.onload = () => resolve(window.Hls);
      fallbackScript.onerror = (e) => reject(new Error('Failed to load Hls.js from CDN: ' + e));
      document.head.appendChild(fallbackScript);
    };
    document.head.appendChild(script);
  });
}

/**
 * Format relative seconds offset as -MM:SS or +MM:SS
 */
function formatOffset(seconds) {
  const abs = Math.abs(Math.round(seconds));
  const m = Math.floor(abs / 60).toString().padStart(2, '0');
  const s = (abs % 60).toString().padStart(2, '0');
  return seconds <= 0 ? `-${m}:${s}` : `+${m}:${s}`;
}

/**
 * Format timestamp as HH:MM:SS
 */
function formatClockTime(date) {
  const d = date instanceof Date ? date : new Date(date);
  return d.toTimeString().split(' ')[0];
}

/**
 * Mounts the Live CCTV Timeshift Player inside a DOM container.
 *
 * @param {HTMLElement|string} containerEl
 * @param {object} options
 * @param {string} options.cameraId
 * @param {string} [options.cameraName]
 * @param {string} [options.apiBaseUrl]
 * @param {Array} [options.cameras]
 * @param {Function} [options.onClose]
 * @returns {object} Controller { destroy, loadCamera, setLive, seekRelative }
 */
export async function mountLiveCctvPlayer(containerEl, options = {}) {
  const container = typeof containerEl === 'string' ? document.querySelector(containerEl) : containerEl;
  if (!container) {
    throw new Error('mountLiveCctvPlayer: Invalid container provided.');
  }

  // Ensure CSS is loaded
  if (!document.getElementById('cctv-player-css')) {
    const link = document.createElement('link');
    link.id = 'cctv-player-css';
    link.rel = 'stylesheet';
    link.href = '/static/components/live-player.css';
    document.head.appendChild(link);
  }

  let currentCameraId = options.cameraId || '';
  let currentCameraName = options.cameraName || currentCameraId;
  const baseUrl = options.apiBaseUrl || (typeof window !== 'undefined' && window.__vyzn_edge_url) || '';
  const camerasList = options.cameras || [];
  const onCloseCallback = options.onClose || null;

  let hlsInstance = null;
  let currentMode = MODE_LIVE;
  let isScrubbing = false;
  let clockInterval = null;
  let rangeInterval = null;
  let serverRange = null;

  // Build DOM Structure
  container.innerHTML = `
    <div class="cctv-player-wrapper" id="cctv-wrapper">
      <div class="cctv-stage" id="cctv-stage">
        <video class="cctv-video-el" id="cctv-video" playsinline muted autoplay></video>

        <!-- OSD Header -->
        <div class="cctv-osd-header">
          <div class="cctv-osd-left">
            <span class="cctv-osd-cam-name" id="cctv-cam-title">${escapeHtml(currentCameraName)}</span>
            <span class="cctv-badge badge-live" id="cctv-mode-badge">
              <span class="badge-dot"></span>
              <span id="cctv-mode-text">LIVE</span>
            </span>
          </div>
          <div class="cctv-osd-right">
            <span class="cctv-osd-clock" id="cctv-clock-text">--:--:--</span>
            <button type="button" class="cctv-btn-close" id="cctv-btn-close" title="Close" aria-label="Close player">✕</button>
          </div>
        </div>

        <!-- Buffering Overlay -->
        <div class="cctv-loading-overlay" id="cctv-buffering" style="display: flex;">
          <div class="cctv-spinner"></div>
          <span class="cctv-loading-text" id="cctv-loading-msg">Connecting to live fMP4 buffer…</span>
        </div>
      </div>

      <!-- Controls Bar -->
      <div class="cctv-controls-bar">
        <!-- Scrubber Timeline -->
        <div class="cctv-timeline-container">
          <div class="cctv-scrubber-track" id="cctv-scrubber-track">
            <div class="cctv-scrubber-buffer" id="cctv-scrubber-buf"></div>
            <div class="cctv-scrubber-played" id="cctv-scrubber-play"></div>
            <div class="cctv-scrubber-thumb" id="cctv-scrubber-thumb"></div>
            <div class="cctv-scrubber-tooltip" id="cctv-scrubber-tooltip">00:00</div>
          </div>
        </div>

        <!-- Action Buttons Row -->
        <div class="cctv-controls-row">
          <div class="cctv-controls-left">
            <button type="button" class="cctv-btn" id="cctv-btn-play" title="Play/Pause">⏸ Pause</button>
            <button type="button" class="cctv-btn" id="cctv-btn-rewind-10" title="Rewind 10 seconds">⏪ 10s</button>
            <button type="button" class="cctv-btn" id="cctv-btn-rewind-30" title="Rewind 30 seconds">⏪ 30s</button>
            <button type="button" class="cctv-btn cctv-btn-live is-active" id="cctv-btn-live" title="Jump to Live Edge">
              <span class="live-dot"></span> LIVE
            </button>
            <span class="cctv-time-display" id="cctv-time-display">
              <span class="time-current" id="cctv-time-curr">LIVE</span>
            </span>
          </div>

          <div class="cctv-controls-right">
            <!-- Camera Switcher -->
            <select class="cctv-cam-select" id="cctv-cam-select" aria-label="Switch Camera">
              <!-- Populated dynamically -->
            </select>
            <button type="button" class="cctv-btn" id="cctv-btn-mute" title="Mute/Unmute">🔇</button>
            <button type="button" class="cctv-btn" id="cctv-btn-fullscreen" title="Fullscreen">⛶</button>
          </div>
        </div>
      </div>
    </div>
  `;

  const video = container.querySelector('#cctv-video');
  const wrapper = container.querySelector('#cctv-wrapper');
  const bufferingOverlay = container.querySelector('#cctv-buffering');
  const loadingMsg = container.querySelector('#cctv-loading-msg');
  const modeBadge = container.querySelector('#cctv-mode-badge');
  const modeText = container.querySelector('#cctv-mode-text');
  const clockText = container.querySelector('#cctv-clock-text');
  const btnClose = container.querySelector('#cctv-btn-close');
  const btnPlay = container.querySelector('#cctv-btn-play');
  const btnRewind10 = container.querySelector('#cctv-btn-rewind-10');
  const btnRewind30 = container.querySelector('#cctv-btn-rewind-30');
  const btnLive = container.querySelector('#cctv-btn-live');
  const timeCurr = container.querySelector('#cctv-time-curr');
  const camSelect = container.querySelector('#cctv-cam-select');
  const btnMute = container.querySelector('#cctv-btn-mute');
  const btnFullscreen = container.querySelector('#cctv-btn-fullscreen');
  const scrubberTrack = container.querySelector('#cctv-scrubber-track');
  const scrubberPlay = container.querySelector('#cctv-scrubber-play');
  const scrubberBuf = container.querySelector('#cctv-scrubber-buf');
  const scrubberThumb = container.querySelector('#cctv-scrubber-thumb');
  const scrubberTooltip = container.querySelector('#cctv-scrubber-tooltip');
  const camTitle = container.querySelector('#cctv-cam-title');

  // Populate camera switcher dropdown
  function updateCameraOptions(list) {
    if (!list || list.length === 0) {
      camSelect.innerHTML = `<option value="${escapeHtml(currentCameraId)}">${escapeHtml(currentCameraName)}</option>`;
      return;
    }
    camSelect.innerHTML = list.map(c => {
      const cid = c.id || c.camera_id;
      const cname = c.name || cid;
      const isSel = cid === currentCameraId ? 'selected' : '';
      return `<option value="${escapeHtml(cid)}" ${isSel}>${escapeHtml(cname)}</option>`;
    }).join('');
  }
  updateCameraOptions(camerasList);

  // If cameras were not passed, fetch from /api/cameras
  if (camerasList.length === 0) {
    fetch(`${baseUrl}/api/cameras?t=${Date.now()}`)
      .then(r => r.json())
      .then(cams => {
        if (Array.isArray(cams) && cams.length > 0) {
          updateCameraOptions(cams);
        }
      })
      .catch(() => {});
  }

  // Real-time clock update
  function tickClock() {
    const now = new Date();
    clockText.textContent = formatClockTime(now);
  }
  tickClock();
  clockInterval = setInterval(tickClock, 1000);

  // Load HLS.js
  const Hls = await ensureHlsScript();

  /**
   * Calculates current seekable start and liveSync edge in seconds.
   */
  function getTimelineBounds() {
    if (!video.seekable || video.seekable.length === 0) {
      const dur = video.duration || 0;
      return { start: 0, end: dur, liveSync: dur };
    }
    const start = video.seekable.start(0);
    const end = video.seekable.end(video.seekable.length - 1);
    const liveSync = (hlsInstance && typeof hlsInstance.liveSyncPosition === 'number' && hlsInstance.liveSyncPosition > 0)
      ? hlsInstance.liveSyncPosition
      : end;
    return { start, end, liveSync };
  }

  /**
   * Sets UI state mode: 'live' vs 'playback'
   */
  function setMode(newMode, offsetSec = 0) {
    currentMode = newMode;
    if (newMode === MODE_LIVE) {
      modeBadge.className = 'cctv-badge badge-live';
      modeText.textContent = 'LIVE';
      btnLive.className = 'cctv-btn cctv-btn-live is-active';
      timeCurr.textContent = 'LIVE';
    } else {
      modeBadge.className = 'cctv-badge badge-playback';
      const offsetStr = formatOffset(offsetSec);
      modeText.textContent = `REPLAY ${offsetStr}`;
      btnLive.className = 'cctv-btn cctv-btn-live is-dimmed';
      timeCurr.textContent = offsetStr;
    }
  }

  /**
   * Updates scrubber timeline bars and thumbs.
   */
  function updateScrubber() {
    if (isScrubbing) return;
    const { start, end, liveSync } = getTimelineBounds();
    const range = Math.max(0.1, liveSync - start);
    const current = Math.max(start, Math.min(video.currentTime, liveSync));

    const playedPct = Math.max(0, Math.min(100, ((current - start) / range) * 100));
    scrubberPlay.style.width = `${playedPct}%`;
    scrubberThumb.style.left = `${playedPct}%`;

    // Buffer range
    if (video.buffered && video.buffered.length > 0) {
      const bufEnd = video.buffered.end(video.buffered.length - 1);
      const bufPct = Math.max(0, Math.min(100, ((bufEnd - start) / range) * 100));
      scrubberBuf.style.width = `${bufPct}%`;
    }

    // Determine if at live edge
    const distFromLive = liveSync - current;
    if (distFromLive <= 2.5) {
      if (currentMode !== MODE_LIVE) setMode(MODE_LIVE);
    } else {
      setMode(MODE_PLAYBACK, -distFromLive);
    }
  }

  /**
   * Initializes or loads a camera HLS stream.
   */
  function loadCamera(camId, camName) {
    currentCameraId = camId;
    currentCameraName = camName || camId;
    camTitle.textContent = currentCameraName;
    bufferingOverlay.style.display = 'flex';
    loadingMsg.textContent = `Connecting to ${currentCameraName}…`;

    if (hlsInstance) {
      hlsInstance.destroy();
      hlsInstance = null;
    }

    const playlistUrl = `${baseUrl}/api/v1/cameras/${camId}/live/live.m3u8`;

    if (Hls.isSupported()) {
      hlsInstance = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        backBufferLength: 900, // 15-minute rolling backbuffer
        liveDurationInfinity: true,
        liveBackBufferLength: 900
      });

      hlsInstance.loadSource(playlistUrl);
      hlsInstance.attachMedia(video);

      hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
        bufferingOverlay.style.display = 'none';
        video.play().catch(() => {});
        setMode(MODE_LIVE);
      });

      hlsInstance.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              loadingMsg.textContent = 'Buffering live feed… retrying';
              setTimeout(() => {
                if (hlsInstance) hlsInstance.startLoad();
              }, 1500);
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              loadingMsg.textContent = 'Recovering media…';
              hlsInstance.recoverMediaError();
              break;
            default:
              bufferingOverlay.style.display = 'none';
              hlsInstance.destroy();
              break;
          }
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Native Safari HLS
      video.src = playlistUrl;
      video.addEventListener('loadedmetadata', () => {
        bufferingOverlay.style.display = 'none';
        video.play().catch(() => {});
        setMode(MODE_LIVE);
      });
    } else {
      bufferingOverlay.style.display = 'flex';
      loadingMsg.textContent = 'HLS playback is not supported on this browser.';
    }

    // Refresh timeshift range telemetry
    fetchRange();
  }

  function fetchRange() {
    fetch(`${baseUrl}/api/v1/cameras/${currentCameraId}/live/range`)
      .then(r => r.json())
      .then(data => {
        serverRange = data;
      })
      .catch(() => {});
  }
  rangeInterval = setInterval(fetchRange, 8000);

  // Jump to Live Edge
  function setLive() {
    const { liveSync } = getTimelineBounds();
    video.currentTime = liveSync;
    video.play().catch(() => {});
    setMode(MODE_LIVE);
    updateScrubber();
  }

  // Seek Relative (-10s, -30s)
  function seekRelative(deltaSeconds) {
    const { start, liveSync } = getTimelineBounds();
    const target = Math.max(start, Math.min(video.currentTime + deltaSeconds, liveSync));
    video.currentTime = target;
    const dist = liveSync - target;
    if (dist <= 2.5) {
      setMode(MODE_LIVE);
    } else {
      setMode(MODE_PLAYBACK, -dist);
    }
    updateScrubber();
  }

  // Scrubber Event Handlers (Click & Drag)
  function handleScrub(e) {
    const rect = scrubberTrack.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const fraction = x / rect.width;
    const { start, liveSync } = getTimelineBounds();
    const target = start + fraction * (liveSync - start);

    // Strictly prevent seeking into the future
    const clampedTarget = Math.max(start, Math.min(target, liveSync));
    video.currentTime = clampedTarget;

    const dist = liveSync - clampedTarget;
    if (dist <= 2.5) {
      setMode(MODE_LIVE);
    } else {
      setMode(MODE_PLAYBACK, -dist);
    }
    updateScrubber();
  }

  scrubberTrack.addEventListener('pointerdown', (e) => {
    isScrubbing = true;
    scrubberTrack.setPointerCapture(e.pointerId);
    handleScrub(e);
  });

  scrubberTrack.addEventListener('pointermove', (e) => {
    if (isScrubbing) {
      handleScrub(e);
    }
    // Hover Tooltip
    const rect = scrubberTrack.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const fraction = x / rect.width;
    const { start, liveSync } = getTimelineBounds();
    const hoverSec = start + fraction * (liveSync - start);
    const dist = liveSync - hoverSec;
    scrubberTooltip.textContent = dist <= 2.5 ? 'LIVE' : formatOffset(-dist);
    scrubberTooltip.style.left = `${fraction * 100}%`;
    scrubberTooltip.style.display = 'block';
  });

  scrubberTrack.addEventListener('pointerup', (e) => {
    if (isScrubbing) {
      isScrubbing = false;
      try { scrubberTrack.releasePointerCapture(e.pointerId); } catch (_) {}
    }
  });

  scrubberTrack.addEventListener('pointerleave', () => {
    if (!isScrubbing) {
      scrubberTooltip.style.display = 'none';
    }
  });

  // Controls Event Listeners
  btnPlay.addEventListener('click', () => {
    if (video.paused) {
      video.play().catch(() => {});
      btnPlay.textContent = '⏸ Pause';
    } else {
      video.pause();
      btnPlay.textContent = '▶ Play';
    }
  });

  video.addEventListener('play', () => { btnPlay.textContent = '⏸ Pause'; });
  video.addEventListener('pause', () => { btnPlay.textContent = '▶ Play'; });
  video.addEventListener('timeupdate', updateScrubber);
  video.addEventListener('waiting', () => { bufferingOverlay.style.display = 'flex'; });
  video.addEventListener('playing', () => { bufferingOverlay.style.display = 'none'; });

  btnRewind10.addEventListener('click', () => seekRelative(-10));
  btnRewind30.addEventListener('click', () => seekRelative(-30));
  btnLive.addEventListener('click', setLive);

  btnMute.addEventListener('click', () => {
    video.muted = !video.muted;
    btnMute.textContent = video.muted ? '🔇' : '🔊';
  });

  btnFullscreen.addEventListener('click', () => {
    if (!document.fullscreenElement) {
      wrapper.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  });

  camSelect.addEventListener('change', (e) => {
    const selId = e.target.value;
    const selOption = e.target.options[e.target.selectedIndex];
    const selName = selOption ? selOption.text : selId;
    loadCamera(selId, selName);
  });

  if (btnClose) {
    btnClose.addEventListener('click', () => {
      destroy();
      if (typeof onCloseCallback === 'function') {
        onCloseCallback();
      }
    });
  }

  // Load initial camera stream
  loadCamera(currentCameraId, currentCameraName);

  function destroy() {
    if (clockInterval) clearInterval(clockInterval);
    if (rangeInterval) clearInterval(rangeInterval);
    if (hlsInstance) {
      hlsInstance.destroy();
      hlsInstance = null;
    }
    video.pause();
    video.src = '';
    container.innerHTML = '';
  }

  return {
    destroy,
    loadCamera,
    setLive,
    seekRelative
  };
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
