import { initShell, promptSecurityPin } from './components/shell.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

let currentChoice = 'ip';
let testedStreamUrl = '';
let testedWidth = 1920;
let testedHeight = 1080;
let testedFps = 20.0;
let createdCameraId = '';

function normalizeUrl(url) {
  if (!url) return '0';
  url = String(url).trim();
  if (url === '0' || url.toLowerCase() === 'webcam') return '0';
  if (!/^https?:\/\//i.test(url) && !/^rtsp:\/\//i.test(url) && !url.startsWith('sim://') && !url.startsWith('test://')) {
    if (url.includes(':8080') || url.includes(':4747') || url.includes(':8081') || url.startsWith('192.168.') || url.startsWith('10.') || url.startsWith('172.')) {
      if (url.includes(':554')) {
        url = 'rtsp://' + url;
      } else {
        url = 'http://' + url;
      }
    } else {
      url = 'rtsp://' + url;
    }
  }
  if (url.includes(':8080') && !url.includes('/video') && !url.includes('/shot.jpg') && !url.includes('/videofeed')) {
    url = url.replace(/\/+$/, '') + '/video';
  } else if (url.includes(':4747') && !url.includes('/video') && !url.includes('/mjpegfeed')) {
    url = url.replace(/\/+$/, '') + '/video';
  }
  return url;
}

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  initShell({ activePage: 'cameras' });

  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = 'Add camera';

  attachStep1Events();
  attachStep2Events();
  attachStep3Events();
  attachStepperNavigation();
  loadCameraQuota();

  window.runConnectionTest = runConnectionTest;
});

let currentQuota = { purchased: 0, used: 0, available: 0 };

async function loadCameraQuota() {
  try {
    let res = await fetch('/billing/quota', { credentials: 'include' });
    if (!res.ok) {
      res = await fetch('/api/billing/quota', { credentials: 'include' });
    }
    if (!res.ok) {
      console.warn('Could not load camera quota from server');
      return;
    }
    const data = await res.json();
    currentQuota = data;

    const valPurchased = document.getElementById('val-addcam-purchased');
    const valUsed = document.getElementById('val-addcam-used');
    const valAvailable = document.getElementById('val-addcam-available');
    const boxAvailable = document.getElementById('box-addcam-available');
    const lblAvailable = document.getElementById('lbl-addcam-available');
    const descAvailable = document.getElementById('desc-addcam-available');

    const summaryEl = document.getElementById('quota-summary-text');
    const subEl = document.getElementById('quota-sub-text');
    const exhaustedCard = document.getElementById('quota-exhausted-card');
    const exhaustedMsg = document.getElementById('quota-exhausted-message');
    const actionBtnWrap = document.getElementById('quota-action-btn-wrap');
    const badgeEl = document.getElementById('quota-remaining-badge');
    const iconBox = document.getElementById('quota-status-icon-box');

    if (valPurchased) valPurchased.textContent = data.purchased;
    if (valUsed) valUsed.textContent = data.used;
    if (valAvailable) valAvailable.textContent = data.available;

    if (summaryEl) {
      summaryEl.textContent = `Camera Quota: ${data.purchased} purchased · ${data.used} used · ${data.available} available`;
    }

    if (data.available > 0) {
      if (subEl) subEl.textContent = `You have ${data.available} remaining slot${data.available > 1 ? 's' : ''}. You can add up to ${data.available} more camera${data.available > 1 ? 's' : ''} to VYZN.`;
      if (badgeEl) {
        badgeEl.textContent = `✓ ${data.available} Slot${data.available > 1 ? 's' : ''} Remaining`;
        badgeEl.style.background = 'rgba(16, 185, 129, 0.15)';
        badgeEl.style.color = '#34d399';
        badgeEl.style.border = '1px solid rgba(16, 185, 129, 0.3)';
      }
      if (iconBox) {
        iconBox.style.background = 'rgba(16, 185, 129, 0.1)';
        iconBox.style.borderColor = 'rgba(16, 185, 129, 0.25)';
      }
      if (boxAvailable) {
        boxAvailable.style.background = 'rgba(16, 185, 129, 0.05)';
        boxAvailable.style.borderColor = 'rgba(16, 185, 129, 0.25)';
      }
      if (lblAvailable) {
        lblAvailable.style.color = '#10b981';
        lblAvailable.textContent = 'Remaining Quota';
      }
      if (valAvailable) valAvailable.style.color = '#10b981';
      if (descAvailable) {
        descAvailable.style.color = '#10b981';
        descAvailable.textContent = 'Available to connect';
      }

      if (exhaustedCard) exhaustedCard.style.display = 'none';
      if (actionBtnWrap) actionBtnWrap.style.display = 'none';
      document.querySelectorAll('.option-card').forEach(btn => {
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
        btn.style.cursor = 'pointer';
        btn.removeAttribute('disabled');
      });
    } else {
      if (subEl) subEl.textContent = `Quota limit reached (${data.used} of ${data.purchased} active). You cannot add more cameras.`;
      if (badgeEl) {
        badgeEl.textContent = '🚫 0 Remaining (Quota Full)';
        badgeEl.style.background = 'rgba(239, 68, 68, 0.15)';
        badgeEl.style.color = '#f87171';
        badgeEl.style.border = '1px solid rgba(239, 68, 68, 0.35)';
      }
      if (iconBox) {
        iconBox.style.background = 'rgba(239, 68, 68, 0.1)';
        iconBox.style.borderColor = 'rgba(239, 68, 68, 0.25)';
      }
      if (boxAvailable) {
        boxAvailable.style.background = 'rgba(239, 68, 68, 0.06)';
        boxAvailable.style.borderColor = 'rgba(239, 68, 68, 0.3)';
      }
      if (lblAvailable) {
        lblAvailable.style.color = '#f87171';
        lblAvailable.textContent = 'Remaining (Full)';
      }
      if (valAvailable) valAvailable.style.color = '#f87171';
      if (descAvailable) {
        descAvailable.style.color = '#f87171';
        descAvailable.textContent = '0 slots remaining';
      }

      if (exhaustedCard) {
        exhaustedCard.style.display = 'block';
        if (exhaustedMsg) {
          exhaustedMsg.textContent = `You have used all ${data.purchased} of your purchased camera slot(s) (${data.used} active, 0 remaining). To connect additional cameras, top up your camera quota in Settings > Camera Plan.`;
        }
      }
      if (actionBtnWrap) actionBtnWrap.style.display = 'block';
      document.querySelectorAll('.option-card').forEach(btn => {
        btn.style.opacity = '0.35';
        btn.style.pointerEvents = 'none';
        btn.style.cursor = 'not-allowed';
        btn.setAttribute('disabled', 'true');
      });
    }
  } catch (err) {
    console.warn('Could not fetch camera quota:', err);
  }
}

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
    card.addEventListener('click', (e) => {
      if (currentQuota && currentQuota.available <= 0) {
        e.preventDefault();
        e.stopPropagation();
        alert('No camera quota available. You have 0 available camera slots. Please add a camera plan in Settings.');
        window.location.href = '/settings#camera-plan';
        return;
      }
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

  // Tab toggle between Webcam and Phone camera in Path C
  let phoneSubChoice = 'webcam';
  const tabWebcam = document.getElementById('tab-opt-webcam');
  const tabPhone = document.getElementById('tab-opt-phone');
  const subWebcam = document.getElementById('subpath-webcam');
  const subPhone = document.getElementById('subpath-phone');

  function setPhoneSubTab(mode) {
    phoneSubChoice = mode;
    if (mode === 'webcam') {
      if (tabWebcam) {
        tabWebcam.style.background = '#3b82f6';
        tabWebcam.style.color = '#ffffff';
        tabWebcam.classList.add('is-active');
      }
      if (tabPhone) {
        tabPhone.style.background = 'transparent';
        tabPhone.style.color = '#a1a1aa';
        tabPhone.classList.remove('is-active');
      }
      if (subWebcam) subWebcam.style.display = 'block';
      if (subPhone) subPhone.style.display = 'none';
    } else {
      if (tabPhone) {
        tabPhone.style.background = '#3b82f6';
        tabPhone.style.color = '#ffffff';
        tabPhone.classList.add('is-active');
      }
      if (tabWebcam) {
        tabWebcam.style.background = 'transparent';
        tabWebcam.style.color = '#a1a1aa';
        tabWebcam.classList.remove('is-active');
      }
      if (subPhone) subPhone.style.display = 'block';
      if (subWebcam) subWebcam.style.display = 'none';
    }
  }

  if (tabWebcam) tabWebcam.addEventListener('click', () => setPhoneSubTab('webcam'));
  if (tabPhone) tabPhone.addEventListener('click', () => setPhoneSubTab('phone'));

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
        runConnectionTest(payload);
      } else if (currentChoice === 'phone') {
        if (phoneSubChoice === 'webcam') {
          testedStreamUrl = '0';
          runConnectionTest({ source_type: 'webcam', rtsp_url: '0' });
        } else {
          const phoneUrl = document.getElementById('phone-stream-url')?.value.trim();
          if (!phoneUrl) {
            displayTestError(
              'Please enter your phone stream address.',
              'Open IP Webcam on your phone, tap "Start server", and enter the address shown (e.g. http://192.168.1.50:8080/video).'
            );
            return;
          }
          const normPhoneUrl = normalizeUrl(phoneUrl);
          payload = { rtsp_url: normPhoneUrl, source_type: 'phone' };
          runConnectionTest(payload);
        }
      } else {
        runConnectionTest({ source_type: 'ip', rtsp_url: '0' });
      }
    });
  }

  // Step 2 Continue Button
  const btnStep2Continue = document.getElementById('btn-step2-continue');
  if (btnStep2Continue) {
    btnStep2Continue.addEventListener('click', () => {
      setWizardStep('step-3', 'Step 3 of 3');
    });
  }

  // Add Camera Anyway (Skip Test button in error container)
  const btnAddAnyway = document.getElementById('btn-add-anyway');
  if (btnAddAnyway) {
    btnAddAnyway.addEventListener('click', () => {
      let rawUrl = testedStreamUrl;
      if (!rawUrl) {
        if (currentChoice === 'phone') {
          rawUrl = document.getElementById('phone-stream-url')?.value.trim() || '';
        } else if (currentChoice === 'ip') {
          rawUrl = document.getElementById('ip-full-url')?.value.trim() || document.getElementById('ip-address')?.value.trim() || '';
        }
      }
      testedStreamUrl = normalizeUrl(rawUrl || '0');
      testedFps = 20.0;
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
  const errorActions = document.getElementById('test-error-actions');
  const resultContainer = document.getElementById('test-result-container');

  resultBox.className = 'test-result-box success';
  msgEl.textContent = params.message || 'We can see the picture.';
  testedWidth = params.width || 1280;
  testedHeight = params.height || 720;
  testedFps = params.fps || 20.0;
  factsEl.textContent = `${testedWidth}×${testedHeight} · ${testedFps} fps`;

  if (params.stream) {
    if (previewVideo) {
      previewVideo.srcObject = params.stream;
      previewVideo.muted = true;
      previewVideo.playsInline = true;
      previewVideo.style.display = 'block';
      previewVideo.play().catch(e => console.warn('Preview video play warning:', e));
      if (thumbImg) thumbImg.style.display = 'none';
      thumbWrap.style.display = 'block';
    }
  } else if (params.preview_base64) {
    if (thumbImg) {
      thumbImg.src = params.preview_base64;
      thumbImg.style.display = 'block';
      if (previewVideo) {
        previewVideo.style.display = 'none';
        if (previewVideo.srcObject) {
          previewVideo.srcObject.getTracks().forEach(t => t.stop());
          previewVideo.srcObject = null;
        }
      }
      thumbWrap.style.display = 'block';
    }
  } else {
    thumbWrap.style.display = 'none';
  }

  if (params.rtsp_url !== undefined) {
    testedStreamUrl = normalizeUrl(params.rtsp_url);
  }
  if (errorActions) errorActions.style.display = 'none';
  continueWrap.style.display = 'block';
  if (resultContainer) resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function displayTestError(msg, detail, targetUrl) {
  const resultBox = document.getElementById('test-result-box');
  const msgEl = document.getElementById('test-result-message');
  const factsEl = document.getElementById('test-result-facts');
  const thumbWrap = document.getElementById('test-preview-thumb');
  const previewVideo = document.getElementById('test-preview-video');
  const thumbImg = document.getElementById('test-preview-img');
  const continueWrap = document.getElementById('test-continue-wrap');
  const errorActions = document.getElementById('test-error-actions');
  const resultContainer = document.getElementById('test-result-container');

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
  if (errorActions) errorActions.style.display = 'block';

  if (targetUrl) {
    testedStreamUrl = normalizeUrl(targetUrl);
    testedFps = 20.0;
  }
  if (resultContainer) resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function testWebcamConnection() {
  const btnTest = document.getElementById('btn-test-connection');
  const resultContainer = document.getElementById('test-result-container');
  const previewVideo = document.getElementById('test-preview-video');
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

      if (previewVideo) {
        previewVideo.srcObject = stream;
        previewVideo.muted = true;
        previewVideo.playsInline = true;
        await previewVideo.play().catch(e => console.warn('Preview play warning:', e));
      }

      await new Promise(r => setTimeout(r, 400));

      const w = (previewVideo && previewVideo.videoWidth) ? previewVideo.videoWidth : 1280;
      const h = (previewVideo && previewVideo.videoHeight) ? previewVideo.videoHeight : 720;
      let b64 = null;
      try {
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        if (previewVideo) ctx.drawImage(previewVideo, 0, 0, w, h);
        b64 = canvas.toDataURL('image/jpeg', 0.85);
      } catch (err) {
        console.warn('Canvas snapshot warning:', err);
      }

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
      if (edgeData.ok && (edgeData.status === 'success' || edgeData.code === 'success')) {
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
    'Please click the camera/lock icon in your browser address bar and choose "Allow" for Camera, or check that a webcam is connected.'
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
          fps: edgeData.fps || 20.0,
          preview_base64: edgeData.preview_base64,
          message: 'We can see the picture.',
          rtsp_url: rawUrl
        });
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
        fps: 20.0,
        preview_base64: b64,
        message: 'We can see the picture.',
        rtsp_url: rawUrl
      });
      btnTest.disabled = false;
      btnTest.textContent = 'Test connection';
      return;
    } catch (err) {
      // Continue to Strategy 3
    }
  }

  let serverErrMsg = '';
  try {
    const res = await fetch('/api/cameras/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({}));
    if (data.ok && (data.status === 'online' || data.status === 'success') && data.preview_base64 && data.preview_base64.length > 500) {
      displayTestSuccess({
        width: data.width || 1920,
        height: data.height || 1080,
        fps: data.fps || 20.0,
        preview_base64: data.preview_base64,
        message: data.message || 'We can see the picture.',
        rtsp_url: rawUrl
      });
      btnTest.disabled = false;
      btnTest.textContent = 'Test connection';
      return;
    } else if (data.message || data.detail) {
      serverErrMsg = data.message || data.detail;
    }
  } catch (err) {
    // Strategy 3 failed
  }

  displayTestError(
    serverErrMsg || `Couldn't reach camera at ${rawUrl}`,
    'Check that camera or phone is turned on and on the same Wi-Fi network. For IP Webcam on Android/iOS, make sure "Start server" is tapped at the bottom of the app and that the IP address matches your phone display. You can also save the camera and start the stream anytime.',
    rawUrl
  );
  btnTest.disabled = false;
  btnTest.textContent = 'Test connection';
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

      if (currentQuota && currentQuota.available <= 0) {
        alert('No camera quota available. You have 0 available camera slots. Please add a camera plan in Settings.');
        window.location.href = '/settings#camera-plan';
        return;
      }

      btnSave.disabled = true;
      btnSave.textContent = 'Saving…';


      // Cleanly release browser webcam tracks so hardware webcam 0 is unlocked
      if (activeWebcamStream) {
        try {
          activeWebcamStream.getTracks().forEach(t => t.stop());
        } catch (e) {}
        activeWebcamStream = null;
      }

      try {
        const payloadData = {
          name: camName,
          rtsp_url: testedStreamUrl || '0',
          target_fps: testedFps || 20.0
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
          if (res.status === 403 && (errData.detail === 'QUOTA_EXHAUSTED' || String(errData.detail).includes('QUOTA'))) {
            alert('No camera quota available. You have reached your camera plan limit. Please visit Settings > Camera Plan to top up your quota.');
            window.location.href = '/settings#camera-plan';
            return;
          }
          throw new Error(errData.detail || 'Save failed');
        }
        const data = await res.json();
        createdCameraId = data.id || data.camera_id;

        // 2. Also register to local edge server if running with identical camera ID
        try {
          await fetch('http://127.0.0.1:8000/api/cameras', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Security-Pin': pin
            },
            body: JSON.stringify({ ...payloadData, id: createdCameraId, camera_id: createdCameraId })
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
