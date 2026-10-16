import { initShell, promptSecurityPin } from './components/shell.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

let currentChoice = 'ip';
let testedStreamUrl = '';
let testedWidth = 1920;
let testedHeight = 1080;
let testedFps = 15.0;
let createdCameraId = '';

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  initShell({ activePage: 'cameras' });

  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = 'Add camera';

  attachStep1Events();
  attachStep2Events();
  attachStep3Events();
  attachStepperNavigation();

  window.runConnectionTest = runConnectionTest;
});

function setWizardStep(stepNum, stepperText) {
  const stepper = document.getElementById('wizard-stepper');
  if (stepper) stepper.textContent = stepperText.toUpperCase();

  const fill = document.getElementById('stepper-progress-fill');
  const counter = document.getElementById('stepper-counter');
  const wrap = document.getElementById('stepper-progress-wrap');

  if (stepNum === 'step-1') {
    if (fill) fill.style.setProperty('width', '33.333%', 'important');
    if (counter) counter.textContent = '1/3';
    if (wrap) wrap.style.display = 'flex';
    if (stepper) stepper.style.display = 'block';
  } else if (stepNum === 'step-2') {
    if (fill) fill.style.setProperty('width', '66.666%', 'important');
    if (counter) counter.textContent = '2/3';
    if (wrap) wrap.style.display = 'flex';
    if (stepper) stepper.style.display = 'block';
  } else if (stepNum === 'step-3') {
    if (fill) fill.style.setProperty('width', '100%', 'important');
    if (counter) counter.textContent = '3/3';
    if (wrap) wrap.style.display = 'flex';
    if (stepper) stepper.style.display = 'block';
  } else if (stepNum === 'step-success') {
    if (wrap) wrap.style.display = 'none';
    if (stepper) stepper.style.display = 'none';
  }

  document.querySelectorAll('.wizard-step').forEach(el => el.style.display = 'none');
  const target = document.getElementById(stepNum);
  if (target) target.style.display = 'block';
}

function attachStepperNavigation() {
  const track = document.getElementById('stepper-progress-track') || document.querySelector('.stepper-progress-track');
  if (track) {
    track.addEventListener('click', (e) => {
      const rect = track.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const ratio = clickX / rect.width;
      if (ratio <= 0.35) {
        setWizardStep('step-1', 'Step 1 of 3');
      } else if (ratio <= 0.70) {
        setWizardStep('step-2', 'Step 2 of 3');
        document.querySelectorAll('.path-section').forEach(s => s.style.display = 'none');
        const pathEl = document.getElementById(`path-${currentChoice}`);
        if (pathEl) pathEl.style.display = 'block';
        if (currentChoice === 'ip') updateAddressPreview();
      } else {
        setWizardStep('step-3', 'Step 3 of 3');
      }
    });
  }

  const counter = document.getElementById('stepper-counter');
  if (counter) {
    counter.addEventListener('click', () => {
      const text = counter.textContent.trim();
      if (text === '1/3') {
        setWizardStep('step-2', 'Step 2 of 3');
        document.querySelectorAll('.path-section').forEach(s => s.style.display = 'none');
        const pathEl = document.getElementById(`path-${currentChoice}`);
        if (pathEl) pathEl.style.display = 'block';
      } else if (text === '2/3') {
        setWizardStep('step-3', 'Step 3 of 3');
      } else {
        setWizardStep('step-1', 'Step 1 of 3');
      }
    });
  }

  const stepper = document.getElementById('wizard-stepper');
  if (stepper) {
    stepper.style.cursor = 'pointer';
    stepper.title = 'Click to return to Step 1';
    stepper.addEventListener('click', () => {
      setWizardStep('step-1', 'Step 1 of 3');
    });
  }

  const btnStep2Back = document.getElementById('btn-step2-back');
  if (btnStep2Back) {
    btnStep2Back.addEventListener('click', () => {
      setWizardStep('step-1', 'Step 1 of 3');
    });
  }

  const btnStep3Back = document.getElementById('btn-step3-back');
  if (btnStep3Back) {
    btnStep3Back.addEventListener('click', () => {
      setWizardStep('step-2', 'Step 2 of 3');
      document.querySelectorAll('.path-section').forEach(s => s.style.display = 'none');
      const pathEl = document.getElementById(`path-${currentChoice}`);
      if (pathEl) pathEl.style.display = 'block';
    });
  }
}


function attachStep1Events() {
  document.querySelectorAll('[data-choice]').forEach(card => {
    card.addEventListener('click', () => {
      currentChoice = card.getAttribute('data-choice');
      setWizardStep('step-2', 'Step 2 of 3');

      document.querySelectorAll('.path-section').forEach(s => s.style.display = 'none');
      const pathEl = document.getElementById(`path-${currentChoice}`);
      if (pathEl) pathEl.style.display = 'block';

      if (currentChoice === 'ip') {
        updateAddressPreview();
      } else if (currentChoice === 'network') {
        startNetworkScan();
      }
    });
  });
}

function updateAddressPreview() {
  const ip = document.getElementById('ip-address')?.value.trim() || '192.168.1.64';
  const port = document.getElementById('ip-port')?.value.trim() || '554';
  const user = document.getElementById('ip-username')?.value.trim() || 'admin';
  const pw = document.getElementById('ip-password')?.value || '';
  const brand = document.getElementById('ip-brand')?.value || 'Hikvision';
  const channel = document.getElementById('ip-channel')?.value || '1';
  const maskedPw = pw ? '••••' : '••••';

  let path = '';
  if (brand === 'Hikvision') {
    path = `/Streaming/Channels/${channel}01`;
  } else if (brand === 'CP Plus' || brand === 'Dahua') {
    path = `/cam/realmonitor?channel=${channel}&subtype=0`;
  } else {
    path = '/';
  }

  const previewEl = document.getElementById('address-preview-text');
  if (previewEl) {
    previewEl.textContent = `rtsp://${user}:${maskedPw}@${ip}:${port}${path}`;
  }
}

function attachStep2Events() {
  // Live input updates for address preview
  ['ip-address', 'ip-port', 'ip-username', 'ip-password', 'ip-brand', 'ip-channel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', updateAddressPreview);
      el.addEventListener('change', updateAddressPreview);
    }
  });

  // Password visibility toggle
  const btnTogglePw = document.getElementById('btn-toggle-pw');
  const inputPw = document.getElementById('ip-password');
  if (btnTogglePw && inputPw) {
    btnTogglePw.addEventListener('click', () => {
      const isPw = inputPw.type === 'password';
      inputPw.type = isPw ? 'text' : 'password';
      btnTogglePw.textContent = isPw ? '🔒' : '👁';
    });
  }

  // Advanced full URL toggle
  const btnAdvanced = document.getElementById('btn-toggle-advanced');
  const groupFullUrl = document.getElementById('group-full-url');
  const standardFields = document.getElementById('ip-standard-fields');
  if (btnAdvanced && groupFullUrl && standardFields) {
    btnAdvanced.addEventListener('click', () => {
      const isAdv = groupFullUrl.style.display !== 'none';
      groupFullUrl.style.display = isAdv ? 'none' : 'block';
      standardFields.style.display = isAdv ? 'block' : 'none';
      btnAdvanced.textContent = isAdv ? 'Advanced: paste a full stream address' : 'Standard IP fields';
    });
  }

  // Network retry and fallback buttons
  const btnNetRetry = document.getElementById('btn-network-retry');
  if (btnNetRetry) btnNetRetry.addEventListener('click', startNetworkScan);

  const btnNetToIp = document.getElementById('btn-network-to-ip');
  if (btnNetToIp) {
    btnNetToIp.addEventListener('click', () => {
      currentChoice = 'ip';
      document.querySelectorAll('.path-section').forEach(s => s.style.display = 'none');
      document.getElementById('path-ip').style.display = 'block';
      updateAddressPreview();
    });
  }

  // Webcam button
  const btnWebcam = document.getElementById('btn-use-webcam');
  if (btnWebcam) {
    btnWebcam.addEventListener('click', () => {
      testedStreamUrl = '0';
      runConnectionTest({ source_type: 'webcam', rtsp_url: '0' });
    });
  }

  // Test Connection Button
  const btnTest = document.getElementById('btn-test-connection');
  if (btnTest) {
    btnTest.addEventListener('click', () => {
      let payload = {};
      if (currentChoice === 'ip') {
        const fullUrlInput = document.getElementById('ip-full-url')?.value.trim();
        if (groupFullUrl.style.display !== 'none' && fullUrlInput) {
          payload = { rtsp_url: fullUrlInput };
        } else {
          payload = {
            ip: document.getElementById('ip-address')?.value.trim() || '192.168.1.64',
            port: parseInt(document.getElementById('ip-port')?.value || '554', 10),
            username: document.getElementById('ip-username')?.value.trim() || 'admin',
            password: document.getElementById('ip-password')?.value || '',
            brand: document.getElementById('ip-brand')?.value || 'Hikvision',
            channel: parseInt(document.getElementById('ip-channel')?.value || '1', 10),
            source_type: 'ip'
          };
        }
      } else if (currentChoice === 'phone') {
        const phoneUrl = document.getElementById('phone-stream-url')?.value.trim();
        payload = { rtsp_url: phoneUrl || 'http://192.168.1.15:8080/video', source_type: 'phone' };
      }
      runConnectionTest(payload);
    });
  }

  // Step 2 Continue Button
  const btnStep2Continue = document.getElementById('btn-step2-continue');
  if (btnStep2Continue) {
    btnStep2Continue.addEventListener('click', () => {
      setWizardStep('step-3', 'Step 3 of 3');
    });
  }
}

async function startNetworkScan() {
  const scanningEl = document.getElementById('network-scanning-state');
  const foundListEl = document.getElementById('network-found-list');
  const emptyEl = document.getElementById('network-empty-state');

  scanningEl.style.display = 'block';
  foundListEl.style.display = 'none';
  emptyEl.style.display = 'none';

  try {
    const res = await fetch('/api/v1/cameras/discover?timeout=2.0');
    const data = await res.json();
    scanningEl.style.display = 'none';

    if (data.cameras && data.cameras.length > 0) {
      foundListEl.innerHTML = data.cameras.map((c, i) => `
        <div class="choice-card" style="display: flex; align-items: center; justify-content: space-between;">
          <div>
            <div class="choice-card-title">${escapeHtml(c.vendor || 'IP Camera')} (${escapeHtml(c.ip)})</div>
            <div class="choice-card-desc mono-facts">${escapeHtml(c.rtsp_url)}</div>
          </div>
          <button type="button" class="btn btn-secondary btn-select-discovered" data-idx="${i}">Select</button>
        </div>
      `).join('');
      foundListEl.style.display = 'flex';

      document.querySelectorAll('.btn-select-discovered').forEach(btn => {
        btn.addEventListener('click', () => {
          const idx = parseInt(btn.getAttribute('data-idx'), 10);
          const selected = data.cameras[idx];
          currentChoice = 'ip';
          document.querySelectorAll('.path-section').forEach(s => s.style.display = 'none');
          document.getElementById('path-ip').style.display = 'block';
          if (document.getElementById('ip-address')) document.getElementById('ip-address').value = selected.ip;
          if (document.getElementById('ip-port')) document.getElementById('ip-port').value = selected.port || 554;
          updateAddressPreview();
        });
      });
    } else {
      emptyEl.style.display = 'flex';
    }
  } catch (err) {
    scanningEl.style.display = 'none';
    emptyEl.style.display = 'flex';
  }
}

let activeWebcamStream = null;

function displayTestSuccess(params) {
  const resultBox = document.getElementById('test-result-box');
  const msgEl = document.getElementById('test-result-message');
  const factsEl = document.getElementById('test-result-facts');
  const thumbWrap = document.getElementById('test-preview-thumb');
  const thumbImg = document.getElementById('test-preview-img');
  const previewVideo = document.getElementById('test-preview-video');
  const continueWrap = document.getElementById('test-continue-wrap');

  resultBox.className = 'test-result-box success';
  msgEl.textContent = params.message || 'We can see the picture.';
  testedWidth = params.width || 1280;
  testedHeight = params.height || 720;
  testedFps = params.fps || 15.0;
  factsEl.textContent = `${testedWidth}×${testedHeight} · ${testedFps} fps`;

  if (params.stream) {
    if (previewVideo) {
      previewVideo.srcObject = params.stream;
      previewVideo.style.display = 'block';
      if (thumbImg) thumbImg.style.display = 'none';
      thumbWrap.style.display = 'block';
    }
  } else if (params.preview_base64) {
    if (thumbImg) {
      thumbImg.src = params.preview_base64;
      thumbImg.style.display = 'block';
      if (previewVideo) previewVideo.style.display = 'none';
      thumbWrap.style.display = 'block';
    }
  } else {
    thumbWrap.style.display = 'none';
  }

  if (params.rtsp_url !== undefined) {
    testedStreamUrl = params.rtsp_url;
  }
  continueWrap.style.display = 'block';
}

function displayTestError(msg, detail) {
  const resultBox = document.getElementById('test-result-box');
  const msgEl = document.getElementById('test-result-message');
  const factsEl = document.getElementById('test-result-facts');
  const thumbWrap = document.getElementById('test-preview-thumb');
  const previewVideo = document.getElementById('test-preview-video');
  const thumbImg = document.getElementById('test-preview-img');
  const continueWrap = document.getElementById('test-continue-wrap');

  resultBox.className = 'test-result-box error';
  msgEl.textContent = msg || 'Connection test failed.';
  factsEl.textContent = detail || '';
  if (previewVideo) {
    previewVideo.style.display = 'none';
    if (previewVideo.srcObject) {
      previewVideo.srcObject.getTracks().forEach(t => t.stop());
      previewVideo.srcObject = null;
    }
  }
  if (thumbImg) thumbImg.style.display = 'none';
  thumbWrap.style.display = 'none';
  continueWrap.style.display = 'none';
}

async function testWebcamConnection() {
  const btnTest = document.getElementById('btn-test-connection');
  const resultContainer = document.getElementById('test-result-container');
  resultContainer.style.display = 'block';
  btnTest.disabled = true;
  btnTest.textContent = 'Accessing webcam…';

  // 1. Try Browser Hardware Camera via WebRTC
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    try {
      if (activeWebcamStream) {
        activeWebcamStream.getTracks().forEach(t => t.stop());
        activeWebcamStream = null;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      activeWebcamStream = stream;

      const video = document.createElement('video');
      video.srcObject = stream;
      video.setAttribute('playsinline', '');
      video.muted = true;
      await video.play();

      await new Promise(r => setTimeout(r, 400));

      const w = video.videoWidth || 1280;
      const h = video.videoHeight || 720;
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, w, h);
      const b64 = canvas.toDataURL('image/jpeg', 0.85);

      displayTestSuccess({
        width: w,
        height: h,
        fps: 30.0,
        stream: stream,
        preview_base64: b64,
        message: 'We can see the picture.',
        rtsp_url: '0'
      });
      btnTest.disabled = false;
      btnTest.textContent = 'Test connection';
      return;
    } catch (err) {
      console.warn('Browser webcam getUserMedia error:', err);
    }
  }

  // 2. Try Local Edge Node on port 8000 (OpenCV device 0)
  try {
    const edgeRes = await fetch('http://127.0.0.1:8000/api/cameras/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_type: 'webcam', rtsp_url: '0' })
    });
    if (edgeRes.ok) {
      const edgeData = await edgeRes.json();
      if (edgeData.ok && edgeData.status === 'success') {
        displayTestSuccess({
          width: edgeData.width || 1280,
          height: edgeData.height || 720,
          fps: edgeData.fps || 15.0,
          preview_base64: edgeData.preview_base64,
          message: 'We can see the picture.',
          rtsp_url: '0'
        });
        btnTest.disabled = false;
        btnTest.textContent = 'Test connection';
        return;
      }
    }
  } catch (e) {
    console.warn('Local edge webcam probe error:', e);
  }

  // 3. Fallback error
  displayTestError(
    'Could not access webcam.',
    'Please allow camera permission in your browser address bar (click the camera/lock icon in URL bar) or connect a webcam.'
  );
  btnTest.disabled = false;
  btnTest.textContent = 'Test connection';
}

async function runConnectionTest(payload) {
  if (payload.source_type === 'webcam' || payload.rtsp_url === '0') {
    return testWebcamConnection();
  }

  const btnTest = document.getElementById('btn-test-connection');
  const resultContainer = document.getElementById('test-result-container');
  btnTest.disabled = true;
  btnTest.textContent = 'Testing connection…';
  resultContainer.style.display = 'block';

  let rawUrl = payload.rtsp_url || '';
  if (!rawUrl && payload.ip) {
    const ip = payload.ip || '192.168.1.64';
    const port = payload.port || 554;
    const user = payload.username || 'admin';
    const pw = payload.password || '';
    const ch = payload.channel || 1;
    const brand = (payload.brand || '').toLowerCase();
    let path = brand.includes('hikvision') ? `/Streaming/Channels/${ch}01` : `/cam/realmonitor?channel=${ch}&subtype=0`;
    rawUrl = `rtsp://${user}:${pw}@${ip}:${port}${path}`;
  }

  // Strategy 1: Test against Local Edge Node (port 8000) for real hardware & LAN OpenCV RTSP/HTTP decoding
  try {
    const edgeRes = await fetch('http://127.0.0.1:8000/api/cameras/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (edgeRes.ok) {
      const edgeData = await edgeRes.json();
      if (edgeData.ok && edgeData.status === 'success') {
        displayTestSuccess({
          width: edgeData.width || 1920,
          height: edgeData.height || 1080,
          fps: edgeData.fps || 15.0,
          preview_base64: edgeData.preview_base64,
          message: 'We can see the picture.',
          rtsp_url: rawUrl
        });
        btnTest.disabled = false;
        btnTest.textContent = 'Test connection';
        return;
      } else if (!edgeData.ok || edgeData.status === 'error') {
        displayTestError(
          edgeData.message || 'Connection test failed.',
          `Camera at ${rawUrl} could not be reached. Check that device is powered on, IP is correct, and on premises Wi-Fi.`
        );
        btnTest.disabled = false;
        btnTest.textContent = 'Test connection';
        return;
      }
    }
  } catch (e) {
    // Local edge node not responding on port 8000
  }

  // Strategy 2: If phone camera HTTP URL (IP Webcam / DroidCam), probe directly over local LAN from browser
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
    let shotUrl = rawUrl;
    if (rawUrl.includes(':8080') && rawUrl.endsWith('/video')) {
      shotUrl = rawUrl.replace(/\/video$/, '/shot.jpg');
    } else if (rawUrl.includes(':8080') && !rawUrl.includes('/shot.jpg')) {
      shotUrl = rawUrl.replace(/\/+$/, '') + '/shot.jpg';
    }

    try {
      const img = await new Promise((resolve, reject) => {
        const testImg = new Image();
        const timeout = setTimeout(() => {
          testImg.src = '';
          reject(new Error('timeout'));
        }, 5000);
        testImg.onload = () => {
          clearTimeout(timeout);
          resolve(testImg);
        };
        testImg.onerror = () => {
          clearTimeout(timeout);
          reject(new Error('unreachable'));
        };
        testImg.src = `${shotUrl}${shotUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
      });

      const w = img.naturalWidth || 1280;
      const h = img.naturalHeight || 720;
      let b64 = img.src;
      try {
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        b64 = canvas.toDataURL('image/jpeg', 0.85);
      } catch (err) {}

      displayTestSuccess({
        width: w,
        height: h,
        fps: 15.0,
        preview_base64: b64,
        message: 'We can see the picture.',
        rtsp_url: rawUrl
      });
      btnTest.disabled = false;
      btnTest.textContent = 'Test connection';
      return;
    } catch (err) {
      displayTestError(
        `Could not reach phone camera at ${rawUrl}`,
        'Make sure: 1. Phone is on same Wi-Fi network. 2. You tapped "Start server" in IP Webcam app. 3. Address exactly matches what is shown on phone screen.'
      );
      btnTest.disabled = false;
      btnTest.textContent = 'Test connection';
      return;
    }
  }

  // Strategy 3: Cloud backend proxy check
  try {
    const res = await fetch('/api/cameras/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok && data.status === 'online') {
      displayTestSuccess({
        width: data.width || 1920,
        height: data.height || 1080,
        fps: data.fps || 15.0,
        preview_base64: data.preview_base64,
        message: data.message || 'We can see the picture.',
        rtsp_url: rawUrl
      });
    } else {
      displayTestError(
        data.message || 'Connection test failed.',
        'Check camera IP, port, credentials, and ensure the local VYZN Edge server (python run_edge.py) is running on your premises computer.'
      );
    }
  } catch (err) {
    displayTestError(
      'Connection test failed.',
      'Check camera address and network. If using a local CCTV camera (192.168.x.x), start the VYZN Edge server on your PC.'
    );
  } finally {
    btnTest.disabled = false;
    btnTest.textContent = 'Test connection';
  }
}

function attachStep3Events() {
  const nameInput = document.getElementById('camera-name-input');
  document.querySelectorAll('.chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (nameInput) nameInput.value = btn.getAttribute('data-suggest');
    });
  });

  const btnStep3Back = document.getElementById('btn-step3-back');
  if (btnStep3Back) {
    btnStep3Back.addEventListener('click', () => {
      setWizardStep('step-2', 'Step 2 of 3');
    });
  }

  const btnSave = document.getElementById('btn-save-camera');
  if (btnSave) {
    btnSave.addEventListener('click', async () => {
      const camName = nameInput ? nameInput.value.trim() || 'Camera 1' : 'Camera 1';

      const pin = await promptSecurityPin({
        title: 'Add Camera',
        description: `Adopt ${camName} and register it to your account. This action requires your 6-digit Security PIN.`,
        confirmText: 'Save Camera',
        isDanger: false
      });
      if (!pin) return;

      btnSave.disabled = true;
      btnSave.textContent = 'Saving…';

      try {
        const payloadData = {
          name: camName,
          rtsp_url: testedStreamUrl || '0',
          target_fps: testedFps
        };

        // 1. Save to cloud server
        const res = await fetch('/api/cameras', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'X-Security-Pin': pin
          },
          body: JSON.stringify(payloadData)
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Save failed');
        }
        const data = await res.json();
        createdCameraId = data.id || data.camera_id;

        // 2. Also register to local edge server if running
        try {
          await fetch('http://127.0.0.1:8000/api/cameras', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Security-Pin': pin
            },
            body: JSON.stringify(payloadData)
          });
        } catch (e) {
          // Local edge not running or already synced
        }

        // Show Success screen
        setWizardStep('step-success', '');
        const headline = document.getElementById('success-headline');
        if (headline) headline.textContent = `${camName} is connected.`;

        const areasLink = document.getElementById('btn-go-to-areas');
        if (areasLink) areasLink.href = `/areas/${encodeURIComponent(createdCameraId)}`;
      } catch (err) {
        alert(err.message || 'Failed to save camera. Try again.');
      } finally {
        btnSave.disabled = false;
        btnSave.textContent = 'Save camera';
      }
    });
  }

  // Add another camera reset
  const btnAddAnother = document.getElementById('btn-add-another');
  if (btnAddAnother) {
    btnAddAnother.addEventListener('click', () => {
      setWizardStep('step-1', 'Step 1 of 3');
      if (nameInput) nameInput.value = 'Camera 1';
      const resultContainer = document.getElementById('test-result-container');
      if (resultContainer) resultContainer.style.display = 'none';
    });
  }
}
