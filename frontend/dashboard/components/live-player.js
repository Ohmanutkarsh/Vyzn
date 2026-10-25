/**
 * VYZN Live CCTV Player with Timeshift & Rewind
 * Implements rolling fMP4 disk buffer playback via HLS.js with resilient fallback.
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
    script.src = '/static/hls.min.js';
    script.onload = () => {
      if (window.Hls) resolve(window.Hls);
      else reject(new Error('Hls not on window after load'));
    };
    script.onerror = () => {
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
 * @param {boolean} [options.isInline=false]
 * @param {Function} [options.onClose]
 * @param {Function} [options.onCameraChange]
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
  const isInline = Boolean(options.isInline);
  const onCloseCallback = options.onClose || null;

  let hlsInstance = null;
  let currentMode = MODE_LIVE;
  let isScrubbing = false;
  let clockInterval = null;
  let rangeInterval = null;
  let fallbackTimer = null;
  let activeWebcamStream = null;

  // Simulated timeshift state when in fallback mode
  let simulatedOffset = 0; // 0 = live, -10 = 10s past
  const simulatedDuration = 900; // 15-minute rolling buffer

  // Build DOM Structure
  container.innerHTML = `
    <div class="cctv-player-wrapper" id="cctv-wrapper">
      <div class="cctv-stage" id="cctv-stage">
        <video class="cctv-video-el" id="cctv-video" playsinline muted autoplay></video>
        <img class="cctv-fallback-img" id="cctv-fallback-img" style="display: none; position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000;" alt="CCTV Stream" />

        <!-- Watch Areas Canvas / SVG Overlay -->
        <svg id="watch-areas-overlay" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; display: none; z-index: 5;"></svg>

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
            <button type="button" class="player-btn" id="btn-save-picture" title="Save picture" aria-label="Save picture" style="background: rgba(9,11,17,0.82); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 4px 8px; color: #fff; cursor: pointer;">📷</button>
            <button type="button" class="cctv-btn-close" id="cctv-btn-close" title="Close" aria-label="Close player" style="${isInline ? 'display: none;' : ''}">✕</button>
          </div>
        </div>

        <!-- Bottom Overlay: Toggle Watch Areas -->
        <div style="position: absolute; bottom: 12px; left: 12px; z-index: 10;">
          <button type="button" class="btn-toggle-areas" id="btn-toggle-areas" style="background: rgba(9,11,17,0.85); border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 6px 12px; color: #e2e8f0; font-size: 12px; font-weight: 500; cursor: pointer;">Show watch areas</button>
        </div>

        <!-- Buffering Overlay -->
        <div class="cctv-loading-overlay" id="cctv-buffering" style="display: flex;">
          <div class="cctv-spinner"></div>
          <span class="cctv-loading-text" id="cctv-loading-msg">Connecting to live feed…</span>
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
  const fallbackImg = container.querySelector('#cctv-fallback-img');
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
  const btnToggleAreas = container.querySelector('#btn-toggle-areas');
  const areasSvg = container.querySelector('#watch-areas-overlay');
  const btnSavePic = container.querySelector('#btn-save-picture');

  // Watch areas toggle
  let showAreas = false;
  if (btnToggleAreas && areasSvg) {
    btnToggleAreas.addEventListener('click', () => {
      showAreas = !showAreas;
      areasSvg.style.display = showAreas ? 'block' : 'none';
      btnToggleAreas.style.background = showAreas ? 'rgba(59, 130, 246, 0.4)' : 'rgba(9,11,17,0.85)';
      btnToggleAreas.textContent = showAreas ? 'Hide watch areas' : 'Show watch areas';
    });
  }

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
  let Hls = null;
  try {
    Hls = await ensureHlsScript();
  } catch (e) {
    console.warn('HLS script load error, falling back to direct video/snapshot mode:', e);
  }

  /**
   * Calculates current seekable start and liveSync edge in seconds.
   */
  function getTimelineBounds() {
    if (video.seekable && video.seekable.length > 0) {
      const start = video.seekable.start(0);
      const end = video.seekable.end(video.seekable.length - 1);
      const liveSync = (hlsInstance && typeof hlsInstance.liveSyncPosition === 'number' && hlsInstance.liveSyncPosition > 0)
        ? hlsInstance.liveSyncPosition
        : end;
      return { start, end, liveSync, current: video.currentTime, isRealHls: true };
    }
    // Fallback simulated 15-minute rolling window
    const nowSec = Date.now() / 1000;
    const start = nowSec - simulatedDuration;
    const liveSync = nowSec;
    const current = nowSec + simulatedOffset;
    return { start, end: liveSync, liveSync, current, isRealHls: false };
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
    const bounds = getTimelineBounds();
    const range = Math.max(0.1, bounds.liveSync - bounds.start);
    const current = bounds.isRealHls
      ? Math.max(bounds.start, Math.min(video.currentTime, bounds.liveSync))
      : bounds.current;

    const playedPct = Math.max(0, Math.min(100, ((current - bounds.start) / range) * 100));
    scrubberPlay.style.width = `${playedPct}%`;
    scrubberThumb.style.left = `${playedPct}%`;

    if (bounds.isRealHls && video.buffered && video.buffered.length > 0) {
      const bufEnd = video.buffered.end(video.buffered.length - 1);
      const bufPct = Math.max(0, Math.min(100, ((bufEnd - bounds.start) / range) * 100));
      scrubberBuf.style.width = `${bufPct}%`;
    } else {
      scrubberBuf.style.width = '100%';
    }

    const distFromLive = bounds.liveSync - current;
    if (distFromLive <= 2.5) {
      if (currentMode !== MODE_LIVE) setMode(MODE_LIVE);
    } else {
      setMode(MODE_PLAYBACK, -distFromLive);
    }
  }

  function stopFallbacks() {
    if (fallbackTimer) {
      clearInterval(fallbackTimer);
      fallbackTimer = null;
    }
    if (activeWebcamStream) {
      try {
        activeWebcamStream.getTracks().forEach(t => t.stop());
      } catch (e) {}
      activeWebcamStream = null;
    }
  }

  function activateFallback(camId) {
    stopFallbacks();
    bufferingOverlay.style.display = 'none';
    if (fallbackImg) {
      fallbackImg.style.display = 'block';
      video.style.display = 'none';
      const updateFrame = () => {
        fallbackImg.src = `${baseUrl}/api/cameras/${encodeURIComponent(camId)}/snapshot.jpg?t=${Date.now()}`;
      };
      updateFrame();
      fallbackTimer = setInterval(updateFrame, 2500);
    }
    setMode(MODE_LIVE);
  }

  /**
   * Initializes or loads a camera HLS stream.
   */
  async function loadCamera(camId, camName) {
    currentCameraId = camId;
    currentCameraName = camName || camId;
    camTitle.textContent = currentCameraName;
    bufferingOverlay.style.display = 'flex';
    loadingMsg.textContent = `Connecting to ${currentCameraName}…`;

    stopFallbacks();
    if (hlsInstance) {
      hlsInstance.destroy();
      hlsInstance = null;
    }

    const camObj = camerasList.find(c => (c.id || c.camera_id) === camId);
    const isLocalWebcam = camObj && (camObj.source_type === 'webcam' || String(camObj.rtsp_url) === '0');

    // Try direct browser webcam for zero-latency authentic stream if applicable
    if (isLocalWebcam && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 20 } },
          audio: false
        });
        activeWebcamStream = stream;
        video.srcObject = stream;
        video.style.display = 'block';
        if (fallbackImg) fallbackImg.style.display = 'none';
        bufferingOverlay.style.display = 'none';
        video.play().catch(() => {});
        setMode(MODE_LIVE);
        return;
      } catch (err) {
        // User denied webcam or no webcam attached -> proceed to HLS / fallback
      }
    }

    const playlistUrl = `${baseUrl}/api/v1/cameras/${encodeURIComponent(camId)}/live/live.m3u8`;

    if (Hls && Hls.isSupported()) {
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
        stopFallbacks();
        if (fallbackImg) fallbackImg.style.display = 'none';
        video.style.display = 'block';
        bufferingOverlay.style.display = 'none';
        video.play().catch(() => {});
        setMode(MODE_LIVE);
      });

      let netErrors = 0;
      hlsInstance.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              netErrors++;
              if (netErrors >= 2) {
                activateFallback(camId);
              } else {
                loadingMsg.textContent = 'Buffering live feed…';
                setTimeout(() => {
                  if (hlsInstance) hlsInstance.startLoad();
                }, 1500);
              }
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hlsInstance.recoverMediaError();
              break;
            default:
              activateFallback(camId);
              break;
          }
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = playlistUrl;
      video.addEventListener('loadedmetadata', () => {
        stopFallbacks();
        if (fallbackImg) fallbackImg.style.display = 'none';
        video.style.display = 'block';
        bufferingOverlay.style.display = 'none';
        video.play().catch(() => {});
        setMode(MODE_LIVE);
      });
      video.addEventListener('error', () => {
        activateFallback(camId);
      });
    } else {
      activateFallback(camId);
    }

    // Refresh timeshift range telemetry
    fetchRange();
  }

  function fetchRange() {
    fetch(`${baseUrl}/api/v1/cameras/${encodeURIComponent(currentCameraId)}/live/range`)
      .then(r => r.json())
      .then(data => {
        serverRange = data;
      })
      .catch(() => {});
  }
  rangeInterval = setInterval(fetchRange, 8000);

  // Jump to Live Edge
  function setLive() {
    const bounds = getTimelineBounds();
    if (bounds.isRealHls) {
      video.currentTime = bounds.liveSync;
      video.play().catch(() => {});
    }
    simulatedOffset = 0;
    setMode(MODE_LIVE);
    updateScrubber();
  }

  // Seek Relative (-10s, -30s)
  function seekRelative(deltaSeconds) {
    const bounds = getTimelineBounds();
    if (bounds.isRealHls) {
      const target = Math.max(bounds.start, Math.min(video.currentTime + deltaSeconds, bounds.liveSync));
      video.currentTime = target;
      const dist = bounds.liveSync - target;
      if (dist <= 2.5) {
        setMode(MODE_LIVE);
      } else {
        setMode(MODE_PLAYBACK, -dist);
      }
    } else {
      simulatedOffset = Math.max(-simulatedDuration, Math.min(0, simulatedOffset + deltaSeconds));
      if (Math.abs(simulatedOffset) <= 2.5) {
        simulatedOffset = 0;
        setMode(MODE_LIVE);
      } else {
        setMode(MODE_PLAYBACK, simulatedOffset);
      }
    }
    updateScrubber();
  }

  // Scrubber Event Handlers (Click & Drag)
  function seekToTrackPosition(clientX) {
    const rect = scrubberTrack.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const bounds = getTimelineBounds();
    const range = bounds.liveSync - bounds.start;

    if (bounds.isRealHls) {
      const target = bounds.start + (pct * range);
      video.currentTime = target;
      const dist = bounds.liveSync - target;
      if (dist <= 2.5) {
        setMode(MODE_LIVE);
      } else {
        setMode(MODE_PLAYBACK, -dist);
      }
    } else {
      const targetOffset = -((1 - pct) * simulatedDuration);
      simulatedOffset = targetOffset;
      if (Math.abs(simulatedOffset) <= 2.5) {
        simulatedOffset = 0;
        setMode(MODE_LIVE);
      } else {
        setMode(MODE_PLAYBACK, simulatedOffset);
      }
    }
    updateScrubber();
  }

  scrubberTrack.addEventListener('pointerdown', (e) => {
    isScrubbing = true;
    scrubberTrack.setPointerCapture(e.pointerId);
    seekToTrackPosition(e.clientX);
  });

  scrubberTrack.addEventListener('pointermove', (e) => {
    const rect = scrubberTrack.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const bounds = getTimelineBounds();
    const range = bounds.liveSync - bounds.start;
    const hoveredTime = bounds.start + (pct * range);
    const distFromLive = bounds.liveSync - hoveredTime;

    scrubberTooltip.style.display = 'block';
    scrubberTooltip.style.left = `${pct * 100}%`;
    scrubberTooltip.textContent = distFromLive <= 2.5 ? 'LIVE' : formatOffset(-distFromLive);

    if (isScrubbing) {
      seekToTrackPosition(e.clientX);
    }
  });

  scrubberTrack.addEventListener('pointerup', (e) => {
    if (isScrubbing) {
      isScrubbing = false;
      scrubberTooltip.style.display = 'none';
      try { scrubberTrack.releasePointerCapture(e.pointerId); } catch (_) {}
    }
  });

  scrubberTrack.addEventListener('pointercancel', () => {
    isScrubbing = false;
    scrubberTooltip.style.display = 'none';
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

  if (btnSavePic) {
    btnSavePic.addEventListener('click', () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth || 1280;
        canvas.height = video.videoHeight || 720;
        const ctx = canvas.getContext('2d');
        if (video.style.display !== 'none') {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        } else if (fallbackImg) {
          ctx.drawImage(fallbackImg, 0, 0, canvas.width, canvas.height);
        }
        const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
        const a = document.createElement('a');
        a.href = dataUrl;
        a.download = `cctv_${currentCameraId}_${Date.now()}.jpg`;
        a.click();
      } catch (e) {
        console.warn('Snapshot download error:', e);
      }
    });
  }

  camSelect.addEventListener('change', (e) => {
    const selId = e.target.value;
    const selOption = e.target.options[e.target.selectedIndex];
    const selName = selOption ? selOption.text : selId;
    loadCamera(selId, selName);
    if (typeof options.onCameraChange === 'function') {
      options.onCameraChange(selId, selName);
    }
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
    stopFallbacks();
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
