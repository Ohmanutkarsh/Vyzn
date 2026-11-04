/**
 * VYZN Live Camera Stream Player
 * Minimal live view: displays clean live camera stream with ONLY a fullscreen option.
 * Export: mountLiveCctvPlayer(container, options)
 */

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
 * Mounts the minimal Live Camera Player inside a DOM container.
 *
 * @param {HTMLElement|string} containerEl
 * @param {object} options
 * @param {string} options.cameraId
 * @param {string} [options.cameraName]
 * @param {string} [options.apiBaseUrl]
 * @param {Array} [options.cameras]
 * @param {Function} [options.onClose]
 * @returns {object} Controller { destroy, loadCamera, toggleFullscreen }
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
    link.href = '/static/components/live-player.css?v=3.0';
    document.head.appendChild(link);
  }

  let currentCameraId = options.cameraId || '';
  let currentCameraName = options.cameraName || currentCameraId;
  const baseUrl = options.apiBaseUrl || (typeof window !== 'undefined' && window.__vyzn_edge_url) || '';
  const camerasList = options.cameras || [];

  let hlsInstance = null;
  let fallbackTimer = null;
  let activeWebcamStream = null;

  // Build clean minimal DOM structure: video stage + loading spinner + ONLY fullscreen button overlay
  container.innerHTML = `
    <div class="cctv-player-wrapper" id="cctv-wrapper">
      <div class="cctv-stage" id="cctv-stage" title="Double-click to toggle full screen">
        <video class="cctv-video-el" id="cctv-video" playsinline muted autoplay></video>
        <img class="cctv-fallback-img" id="cctv-fallback-img" style="display: none; position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000;" alt="Live Camera" />

        <!-- Buffering / Connecting Overlay -->
        <div class="cctv-loading-overlay" id="cctv-buffering" style="display: flex;">
          <div class="cctv-spinner"></div>
          <span class="cctv-loading-text" id="cctv-loading-msg">Connecting to live feed…</span>
        </div>

        <!-- The ONLY control: Fullscreen Button Overlay -->
        <button type="button" class="cctv-fullscreen-btn-overlay" id="cctv-btn-fullscreen" title="Full screen (F)" aria-label="Toggle Full screen">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="fs-icon-enter">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>
          </svg>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="fs-icon-exit" style="display: none;">
            <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path>
          </svg>
        </button>
      </div>
    </div>
  `;

  const video = container.querySelector('#cctv-video');
  const fallbackImg = container.querySelector('#cctv-fallback-img');
  const wrapper = container.querySelector('#cctv-wrapper');
  const stage = container.querySelector('#cctv-stage');
  const bufferingOverlay = container.querySelector('#cctv-buffering');
  const loadingMsg = container.querySelector('#cctv-loading-msg');
  const btnFullscreen = container.querySelector('#cctv-btn-fullscreen');
  const iconEnter = btnFullscreen.querySelector('.fs-icon-enter');
  const iconExit = btnFullscreen.querySelector('.fs-icon-exit');

  // Load HLS.js
  let Hls = null;
  try {
    Hls = await ensureHlsScript();
  } catch (e) {
    console.warn('HLS script load error, falling back to direct video/snapshot mode:', e);
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
    if (bufferingOverlay) bufferingOverlay.style.display = 'none';
    if (fallbackImg) {
      fallbackImg.style.display = 'block';
      if (video) video.style.display = 'none';
      const updateFrame = () => {
        fallbackImg.src = `${baseUrl}/api/cameras/${encodeURIComponent(camId)}/snapshot.jpg?t=${Date.now()}`;
      };
      updateFrame();
      fallbackTimer = setInterval(updateFrame, 1500);
    }
  }

  /**
   * Initializes or loads a camera live stream.
   */
  async function loadCamera(camId, camName) {
    currentCameraId = camId;
    currentCameraName = camName || camId;
    if (bufferingOverlay) bufferingOverlay.style.display = 'flex';
    if (loadingMsg) loadingMsg.textContent = `Connecting to ${currentCameraName}…`;

    stopFallbacks();
    if (hlsInstance) {
      hlsInstance.destroy();
      hlsInstance = null;
    }

    const camObj = camerasList.find(c => (c.id || c.camera_id) === camId);
    const isLocalWebcam = camObj && (camObj.source_type === 'webcam' || String(camObj.rtsp_url) === '0');

    // Direct browser webcam for zero-latency local stream
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
        if (bufferingOverlay) bufferingOverlay.style.display = 'none';
        video.play().catch(() => {});
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
        backBufferLength: 30,
        liveDurationInfinity: true
      });

      hlsInstance.loadSource(playlistUrl);
      hlsInstance.attachMedia(video);

      hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
        stopFallbacks();
        video.style.display = 'block';
        if (fallbackImg) fallbackImg.style.display = 'none';
        video.play().catch(() => {});
        if (bufferingOverlay) bufferingOverlay.style.display = 'none';
      });

      hlsInstance.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              activateFallback(camId);
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hlsInstance.recoverMediaError();
              break;
            default:
              hlsInstance.destroy();
              activateFallback(camId);
              break;
          }
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = playlistUrl;
      video.addEventListener('loadedmetadata', () => {
        stopFallbacks();
        video.style.display = 'block';
        if (fallbackImg) fallbackImg.style.display = 'none';
        video.play().catch(() => {});
        if (bufferingOverlay) bufferingOverlay.style.display = 'none';
      });
      video.addEventListener('error', () => {
        activateFallback(camId);
      });
    } else {
      activateFallback(camId);
    }
  }

  // Fullscreen management
  function isFullscreen() {
    return Boolean(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement);
  }

  function updateFullscreenIcons() {
    const fs = isFullscreen();
    if (iconEnter) iconEnter.style.display = fs ? 'none' : 'block';
    if (iconExit) iconExit.style.display = fs ? 'block' : 'none';
  }

  function toggleFullscreen() {
    if (!isFullscreen()) {
      const target = wrapper || stage;
      if (target.requestFullscreen) {
        target.requestFullscreen().catch(() => {});
      } else if (target.webkitRequestFullscreen) {
        target.webkitRequestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
    }
  }

  // Double click on stage toggles fullscreen
  stage.addEventListener('dblclick', (e) => {
    e.preventDefault();
    toggleFullscreen();
  });

  // Fullscreen button click
  btnFullscreen.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleFullscreen();
  });

  document.addEventListener('fullscreenchange', updateFullscreenIcons);
  document.addEventListener('webkitfullscreenchange', updateFullscreenIcons);

  // Key handler for 'F'
  function handleKeyDown(e) {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) return;
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      toggleFullscreen();
    }
  }
  window.addEventListener('keydown', handleKeyDown);

  // Load initial camera
  loadCamera(currentCameraId, currentCameraName);

  function destroy() {
    stopFallbacks();
    document.removeEventListener('fullscreenchange', updateFullscreenIcons);
    document.removeEventListener('webkitfullscreenchange', updateFullscreenIcons);
    window.removeEventListener('keydown', handleKeyDown);
    if (hlsInstance) {
      hlsInstance.destroy();
      hlsInstance = null;
    }
    video.pause();
    video.src = '';
    video.srcObject = null;
    container.innerHTML = '';
  }

  return {
    destroy,
    loadCamera,
    toggleFullscreen
  };
}
