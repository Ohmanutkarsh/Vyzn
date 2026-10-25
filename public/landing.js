/* ==========================================================================
   VYZN — Security-Tech Landing Page Interactive Controller
   Handles live widgets, simulator state machine, incident replay, 
   real-time telemetry tickers, and storage savings calculator.
   ========================================================================== */

(function () {
  'use strict';

  // 1. Live Frame Counter Simulation
  function initLiveCounters() {
    let baseFrames = 2481093;
    const tickerElements = document.querySelectorAll('[data-live-frames]');
    
    setInterval(() => {
      // Add random 2-6 frames every 200ms (approx 20-30 frames/sec)
      baseFrames += Math.floor(Math.random() * 5) + 2;
      const formatted = baseFrames.toLocaleString('en-US');
      tickerElements.forEach(el => {
        el.textContent = formatted;
      });
    }, 200);
  }

  // 2. Interactive Product Walkthrough Tabs (Detect, Decide, Preserve)
  function initWorkflowSimulator() {
    const tabButtons = document.querySelectorAll('[data-workflow-tab]');
    const hudBox = document.getElementById('sim-bounding-box');
    const hudTag = document.getElementById('sim-bounding-tag');
    const dossierTitle = document.getElementById('sim-dossier-title');
    const dossierSev = document.getElementById('sim-dossier-sev');
    const dossierMeta = document.getElementById('sim-dossier-meta');
    const dossierAction = document.getElementById('sim-dossier-action');

    const states = {
      detect: {
        tag: 'PERSON DETECTED · 0.96',
        color: 'var(--accent-lime)',
        borderColor: 'var(--accent-lime)',
        boxShadow: '0 0 16px rgba(212, 249, 56, 0.4)',
        title: 'Real-Time Edge Computer Vision',
        sev: 'TIER 1 (CONFIRMED)',
        sevClass: 'sim-badge green',
        meta: [
          { label: 'Ingestion Feed', val: 'CAM-04 (Perimeter West) · RTSP H.265' },
          { label: 'Edge Inference Time', val: '18.4ms (YOLOv8 Edge Acceleration)' },
          { label: 'Class Identification', val: 'Human Subject (0.96), Backpack (0.84)' }
        ],
        action: 'Analyzing subject trajectory & loitering interval…'
      },
      decide: {
        tag: 'SECURITY BREACH · TIER 1',
        color: 'var(--accent-red)',
        borderColor: 'var(--accent-red)',
        boxShadow: '0 0 20px rgba(255, 71, 87, 0.5)',
        title: 'Automated Tier-Based Incident Triage',
        sev: 'HIGH SEVERITY',
        sevClass: 'sim-badge red',
        meta: [
          { label: 'Rule Triggered', val: 'Restricted Zone Perimeter Breach (After Hours)' },
          { label: 'Loitering Duration', val: '4 minutes 12 seconds' },
          { label: 'Confidence Score', val: '0.97 (Multi-frame verification)' }
        ],
        action: 'Preparing Telegram alert payload & evidence dossier…'
      },
      preserve: {
        tag: '4K EVIDENCE LOCKED',
        color: '#2ed573',
        borderColor: '#2ed573',
        boxShadow: '0 0 18px rgba(46, 213, 115, 0.4)',
        title: 'Smart Preservation & 72-Hour DPDP Purge',
        sev: 'CONTAINED & LOGGED',
        sevClass: 'sim-badge green',
        meta: [
          { label: 'Evidence Pack', val: '4K 60fps clip locked (Incident INC-2291)' },
          { label: 'Alert Delivery', val: 'Telegram & SMS dispatched in 1.4s' },
          { label: 'Storage Retention', val: 'Non-event baseline queued for 72h hard-purge' }
        ],
        action: 'Evidence export ready. Storage footprint reduced by 94.2%.'
      }
    };

    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const step = btn.getAttribute('data-workflow-tab');
        
        // Update active tab buttons
        tabButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Apply state data
        const data = states[step];
        if (!data) return;

        if (hudBox) {
          hudBox.style.borderColor = data.borderColor;
          hudBox.style.boxShadow = data.boxShadow;
        }
        if (hudTag) {
          hudTag.textContent = data.tag;
          hudTag.style.background = data.color;
          hudTag.style.color = (step === 'decide') ? '#ffffff' : '#000000';
        }
        if (dossierTitle) dossierTitle.textContent = data.title;
        if (dossierSev) {
          dossierSev.textContent = data.sev;
          dossierSev.className = data.sevClass;
        }
        if (dossierMeta) {
          dossierMeta.innerHTML = data.meta.map(m => `
            <div class="sim-meta-item">
              <span>${m.label}</span>
              <strong>${m.val}</strong>
            </div>
          `).join('');
        }
        if (dossierAction) dossierAction.textContent = data.action;
      });
    });
  }

  // 3. Incident Replay Terminal Animation
  function initTerminalReplay() {
    const replayContainer = document.getElementById('terminal-log-stream');
    const replayBtn = document.getElementById('btn-run-replay');
    if (!replayContainer) return;

    const logSequence = [
      { ts: '03:12:07.214', tag: 'detect', class: 'detect', text: '<strong>rtsp.cam04:</strong> motion detected at Perimeter West (1080p stream)' },
      { ts: '03:12:07.380', tag: 'detect', class: 'detect', text: '<strong>yolov8.infer:</strong> human subject classified · confidence 0.96 · 18ms' },
      { ts: '03:12:08.002', tag: 'triage', class: 'triage', text: '<strong>triage.engine:</strong> cross-referenced schedule: after-hours restricted zone' },
      { ts: '03:12:11.640', tag: 'triage', class: 'triage', text: '<strong>triage.verdict:</strong> Tier 1 Security Breach (+0.97 confidence) · 36 frames' },
      { ts: '03:12:15.230', tag: 'action', class: 'action', text: '<strong>alert.bot:</strong> Telegram dispatch to on-call guard with 5s preview GIF' },
      { ts: '03:12:39.482', tag: 'action', class: 'action', text: '<strong>guard.ack:</strong> alert acknowledged by Duty Officer R. Sharma from phone' },
      { ts: '03:12:41.010', tag: 'archive', class: 'archive', text: '<strong>evidence.pack:</strong> locked full 4K 60fps incident video (hash: e3b0c442…)' },
      { ts: '03:12:48.119', tag: 'archive', class: 'archive', text: '<strong>purge.queue:</strong> 42 min empty baseline footage scheduled for 72h purge ✓' }
    ];

    function runAnimation() {
      replayContainer.innerHTML = '';
      logSequence.forEach((item, idx) => {
        setTimeout(() => {
          const row = document.createElement('div');
          row.className = 'term-row';
          row.innerHTML = `
            <span class="term-ts">${item.ts}</span>
            <span class="term-tag ${item.class}">${item.tag}</span>
            <span class="term-msg">${item.text}</span>
          `;
          replayContainer.appendChild(row);
          replayContainer.scrollTop = replayContainer.scrollHeight;
        }, idx * 450);
      });
    }

    if (replayBtn) {
      replayBtn.addEventListener('click', runAnimation);
    }

    // Run automatically once on view
    runAnimation();
  }

  // 4. Multi-Camera Switcher in Capabilities Widget
  function initCameraSwitcher() {
    const camButtons = document.querySelectorAll('[data-cam-target]');
    const camFeedName = document.getElementById('cap-cam-name');
    const camLocation = document.getElementById('cap-cam-location');
    const camStatus = document.getElementById('cap-cam-status');

    const camData = {
      cam1: { name: 'CAM-01', loc: 'Main Reception & Turnstiles', status: 'Optimal · 18ms latency' },
      cam2: { name: 'CAM-02', loc: 'Warehouse Bay 3 Loading Dock', status: 'Optimal · 22ms latency' },
      cam3: { name: 'CAM-03', loc: 'Perimeter West Fence Line', status: 'Alert Active · Loitering Tag' },
      cam4: { name: 'CAM-04', loc: 'Server Room & Telecom Rack', status: 'Restricted · Zero Activity' }
    };

    camButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.getAttribute('data-cam-target');
        camButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const info = camData[target];
        if (info) {
          if (camFeedName) camFeedName.textContent = info.name;
          if (camLocation) camLocation.textContent = info.loc;
          if (camStatus) camStatus.textContent = info.status;
        }
      });
    });
  }

  // 5. Interactive Human Approval Button in Widget 6
  function initApprovalButton() {
    const btn = document.getElementById('btn-interactive-approval');
    const statusNote = document.getElementById('approval-status-note');
    if (!btn) return;

    btn.addEventListener('click', () => {
      btn.classList.add('executed');
      btn.textContent = '✓ Action Executed · Telegram Alert Sent';
      if (statusNote) {
        statusNote.textContent = 'INC-2291 locked in 4K. Reversible for 24 hours in audit log.';
        statusNote.style.color = 'var(--accent-lime)';
      }
    });
  }

  // 6. Interactive Storage Savings Calculator
  function initStorageCalculator() {
    const slider = document.getElementById('cam-count-slider');
    const camDisplay = document.getElementById('calc-cam-display');
    const rawStorageDisplay = document.getElementById('calc-raw-storage');
    const vyznStorageDisplay = document.getElementById('calc-vyzn-storage');
    const annualSavingsDisplay = document.getElementById('calc-annual-savings');
    const hoursSavedDisplay = document.getElementById('calc-hours-saved');

    if (!slider) return;

    function updateCalculations() {
      const cams = parseInt(slider.value, 10);
      if (camDisplay) camDisplay.textContent = cams + ' Cameras';

      // 1 camera 1080p 24/7 generates ~1.44 TB per month
      const rawMonthlyTB = (cams * 1.44).toFixed(1);
      // VYZN retains only ~8% relevant footage + lightweight smart indexed frames
      const vyznMonthlyTB = (cams * 1.44 * 0.08).toFixed(1);
      
      // Saved TB per year
      const savedTBMonthly = cams * 1.44 * 0.92;
      // Average drive & cloud egress cost: ~$40 per TB
      const annualDollarSavings = Math.round(savedTBMonthly * 40 * 12);
      // Average 14 hours per month per 10 cameras spent scrubbing video
      const annualScrubbingHours = Math.round((cams / 10) * 14 * 12);

      if (rawStorageDisplay) rawStorageDisplay.textContent = `${rawMonthlyTB} TB / mo`;
      if (vyznStorageDisplay) vyznStorageDisplay.textContent = `${vyznMonthlyTB} TB / mo`;
      if (annualSavingsDisplay) annualSavingsDisplay.textContent = `$${annualDollarSavings.toLocaleString('en-US')}`;
      if (hoursSavedDisplay) hoursSavedDisplay.textContent = `${annualScrubbingHours.toLocaleString('en-US')} hrs / yr`;
    }

    slider.addEventListener('input', updateCalculations);
    updateCalculations();
  }

  // 7. Free Audit Form Submission
  function initAuditForm() {
    const form = document.getElementById('audit-request-form');
    const successMsg = document.getElementById('audit-form-success');
    if (!form) return;

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const email = form.querySelector('input[type="email"]')?.value || '';
      if (!email) return;

      form.style.display = 'none';
      if (successMsg) {
        successMsg.style.display = 'block';
      }
    });
  }

  // Initialize all controllers on DOM ready
  document.addEventListener('DOMContentLoaded', () => {
    initLiveCounters();
    initWorkflowSimulator();
    initTerminalReplay();
    initCameraSwitcher();
    initApprovalButton();
    initStorageCalculator();
    initAuditForm();
  });
})();
