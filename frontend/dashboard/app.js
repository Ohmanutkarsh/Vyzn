/**
 * VYZN Netra Web Dashboard Client Application.
 * Zero-dependency modern Vanilla JS.
 */

let activeCamera = "cam_corridor";
let currentModalEventId = null;

// DOM Elements
const streamImg = document.getElementById("live-stream-img");
const activeCamTag = document.getElementById("active-cam-tag");
const meterScoreText = document.getElementById("meter-score-text");
const meterBarFill = document.getElementById("meter-bar-fill");
const eventsList = document.getElementById("events-list");
const verifiedCountElem = document.getElementById("verified-alerts-count");
const diskFreeElem = document.getElementById("disk-free-display");
const clockElem = document.getElementById("clock");
const videoModal = document.getElementById("video-modal");
const modalVideo = document.getElementById("modal-video");
const modalTitle = document.getElementById("modal-title");
const modalMeta = document.getElementById("modal-meta");
const btnModalStar = document.getElementById("btn-modal-star");

// Clock update
function updateClock() {
  const now = new Date();
  clockElem.textContent = now.toUTCString().slice(17, 25) + " UTC";
}
setInterval(updateClock, 1000);
updateClock();

// Camera Tab Switching
document.querySelectorAll(".cam-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".cam-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    activeCamera = tab.getAttribute("data-cam");
    activeCamTag.textContent = `LIVE: ${tab.textContent}`;
    streamImg.src = `/api/cameras/${activeCamera}/mjpeg?t=${Date.now()}`;
  });
});

// Fetch System Status & Telemetry
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    if (data.disk_free_pct !== undefined) {
      diskFreeElem.textContent = `${data.disk_free_pct}%`;
    }

    if (data.pipeline) {
      const activeCams = data.pipeline.active_cameras || 3;
      document.getElementById("active-cameras-count").textContent = `${activeCams} / 3`;
    }
  } catch (err) {
    console.debug("Status fetch error:", err);
  }
}

// Fetch Live Hardware & System Metrics
async function fetchTelemetry() {
  try {
    const res = await fetch("/api/system/metrics");
    if (!res.ok) return;
    const data = await res.json();

    const cpuElem = document.getElementById("telemetry-cpu");
    if (cpuElem && data.cpu_percent !== undefined) cpuElem.textContent = `${data.cpu_percent}%`;

    const ramElem = document.getElementById("telemetry-ram");
    if (ramElem && data.ram_used_mb !== undefined) ramElem.textContent = `${data.ram_used_mb} MB (${data.ram_percent}%)`;

    const diskElem = document.getElementById("telemetry-disk");
    if (diskElem && data.disk_free_gb !== undefined) diskElem.textContent = `${data.disk_free_gb} GB`;

    const fpsElem = document.getElementById("telemetry-fps");
    if (fpsElem && data.pipeline_fps !== undefined) fpsElem.textContent = data.pipeline_fps;

    const farElem = document.getElementById("telemetry-far");
    if (farElem && data.triage_stats) {
      farElem.textContent = `${data.triage_stats.false_positive_rate}%`;
    }
  } catch (err) {
    console.debug("Telemetry fetch error:", err);
  }
}

// Handle User Incident Triage
async function setEventTriage(eventId, triageDecision) {
  try {
    const res = await fetch(`/api/events/${eventId}/triage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ triage: triageDecision })
    });
    if (res.ok) {
      fetchEvents();
      fetchTelemetry();
    }
  } catch (err) {
    console.error("Triage update error:", err);
  }
}

// Fetch and Render Events
async function fetchEvents() {
  try {
    const res = await fetch("/api/events?limit=25");
    if (!res.ok) return;
    const events = await res.json();

    if (!events || events.length === 0) {
      eventsList.innerHTML = '<div class="empty-state">No incidents recorded yet. System monitoring active.</div>';
      meterScoreText.textContent = "0 / 100";
      meterBarFill.style.width = "0%";
      return;
    }

    // Update Threat Meter with highest score from recent events
    const latestScore = events[0].score || 0;
    meterScoreText.textContent = `${latestScore} / 100`;
    meterBarFill.style.width = `${latestScore}%`;

    // Count verified alerts (>= 70)
    const verified = events.filter(e => e.score >= 70).length;
    verifiedCountElem.textContent = verified;

    eventsList.innerHTML = "";
    events.forEach(ev => {
      const card = document.createElement("div");
      card.className = `event-card ${ev.score >= 70 ? 'alert-fired' : ''}`;

      const isHigh = ev.score >= 70;
      const timeStr = ev.start_time ? new Date(ev.start_time).toLocaleTimeString() : "";

      let triageHtml = '';
      if (ev.user_triage === 'confirmed_threat') {
        triageHtml = '<span class="badge-threat">✅ Confirmed Threat</span>';
      } else if (ev.user_triage === 'false_positive') {
        triageHtml = '<span class="badge-false">❌ False Alarm</span>';
      } else {
        triageHtml = `
          <div class="event-triage-actions">
            <button class="btn-triage btn-triage-threat" data-id="${ev.event_group_id}">✅ Threat</button>
            <button class="btn-triage btn-triage-false" data-id="${ev.event_group_id}">❌ False Alarm</button>
          </div>
        `;
      }

      card.innerHTML = `
        <img class="event-thumb" src="/api/events/${ev.event_group_id}/thumb" alt="Thumb" onerror="this.src='/static/styles.css'">
        <div class="event-details">
          <div class="event-header">
            <span class="event-camera">${ev.camera_id}</span>
            <span class="event-badge ${isHigh ? 'badge-high' : 'badge-normal'}">${ev.score}/100</span>
          </div>
          <div class="event-body">
            <strong>${ev.object_type ? ev.object_type.toUpperCase() : 'MOTION'}</strong>
            <span>(${(ev.confidence * 100).toFixed(0)}% conf)</span>
          </div>
          <div class="event-footer">
            <span>${timeStr}</span>
            <button class="btn-star-mini" data-id="${ev.event_group_id}">
              ${ev.starred ? '⭐' : '☆'}
            </button>
          </div>
          ${triageHtml}
        </div>
      `;

      // Click card to open video replay
      card.addEventListener("click", (e) => {
        if (e.target.classList.contains("btn-star-mini") || e.target.classList.contains("btn-triage")) return;
        openModal(ev);
      });

      // Star button
      const starBtn = card.querySelector(".btn-star-mini");
      starBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleStar(ev.event_group_id, starBtn);
      });

      // Triage buttons
      const threatBtn = card.querySelector(".btn-triage-threat");
      if (threatBtn) {
        threatBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          setEventTriage(ev.event_group_id, "confirmed_threat");
        });
      }
      const falseBtn = card.querySelector(".btn-triage-false");
      if (falseBtn) {
        falseBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          setEventTriage(ev.event_group_id, "false_positive");
        });
      }

      eventsList.appendChild(card);
    });

  } catch (err) {
    console.debug("Events fetch error:", err);
  }
}


// Modal Handlers
function openModal(event) {
  currentModalEventId = event.event_group_id;
  modalTitle.textContent = `Incident ${event.event_group_id} — Score: ${event.score}/100`;
  modalVideo.src = `/api/events/${event.event_group_id}/clip`;
  modalMeta.innerHTML = `
    <div><strong>Camera:</strong> ${event.camera_id}</div>
    <div><strong>Detected Object:</strong> ${event.object_type} (${(event.confidence * 100).toFixed(0)}% confidence)</div>
    <div><strong>Recorded At:</strong> ${event.start_time}</div>
    <div><strong>Storage Path:</strong> <code>${event.file_path}</code></div>
  `;
  btnModalStar.textContent = event.starred ? "⭐ Starred (Protected)" : "⭐ Star (Protect from Reaper)";
  videoModal.style.display = "flex";
}

function closeModal() {
  videoModal.style.display = "none";
  modalVideo.pause();
  modalVideo.src = "";
  currentModalEventId = null;
}

document.getElementById("btn-close-modal").addEventListener("click", closeModal);
document.getElementById("btn-modal-close-action").addEventListener("click", closeModal);
videoModal.addEventListener("click", (e) => {
  if (e.target === videoModal) closeModal();
});

// Toggle Star Action
async function toggleStar(eventId, btnElem) {
  try {
    const res = await fetch(`/api/events/${eventId}/star`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      if (btnElem) {
        btnElem.textContent = data.starred ? '⭐' : '☆';
      }
      if (currentModalEventId === eventId) {
        btnModalStar.textContent = data.starred ? "⭐ Starred (Protected)" : "⭐ Star (Protect from Reaper)";
      }
    }
  } catch (err) {
    console.error("Star toggle error:", err);
  }
}

btnModalStar.addEventListener("click", () => {
  if (currentModalEventId) toggleStar(currentModalEventId);
});

document.getElementById("btn-refresh-events").addEventListener("click", fetchEvents);

// ---------------------------------------------------------------------------
// Interactive Polygon Zone Drawer
// ---------------------------------------------------------------------------
const zoneModal = document.getElementById("zone-modal");
const zoneCanvas = document.getElementById("zone-canvas");
const ctx = zoneCanvas.getContext("2d");
const btnOpenZoneDrawer = document.getElementById("btn-open-zone-drawer");
const btnOpenPrivacyDrawer = document.getElementById("btn-open-privacy-drawer");
const btnCloseZoneModal = document.getElementById("btn-close-zone-modal");
const btnClearZone = document.getElementById("btn-clear-zone");
const btnSaveZone = document.getElementById("btn-save-zone");
const zoneNameInput = document.getElementById("zone-name-input");
const zoneWeightInput = document.getElementById("zone-weight-input");
const zoneScheduleSelect = document.getElementById("zone-schedule-select");
const zoneTypeSelect = document.getElementById("zone-type-select");
const zoneModalTitle = document.getElementById("zone-modal-title");
const zoneInstructionText = document.getElementById("zone-instruction-text");

let zonePoints = [];
let baseSnapshot = new Image();

function openZoneDrawer(isPrivacy = false) {
  if (isPrivacy) {
    zoneTypeSelect.value = "privacy_mask";
    zoneModalTitle.textContent = `DPDP 2023 Privacy Mask Drawer — [${activeCamera}]`;
    zoneNameInput.value = `${activeCamera}_privacy_mask`;
    if (zoneInstructionText) {
      zoneInstructionText.textContent = "Click 3 or more points to outline an area to permanently blur on live feeds and recordings (e.g. neighbor window, public road).";
    }
  } else {
    zoneTypeSelect.value = "restricted_zone";
    zoneModalTitle.textContent = `Interactive Zone Polygon Drawer — [${activeCamera}]`;
    zoneNameInput.value = `${activeCamera}_restricted_zone`;
    if (zoneInstructionText) {
      zoneInstructionText.textContent = "Click 3 or more points on the camera frame to outline a restricted security threat zone (e.g. Cash Drawer, Rear Shutter, Safe Vault).";
    }
  }
  zonePoints = [];

  // Load current camera snapshot onto canvas
  baseSnapshot = new Image();
  baseSnapshot.crossOrigin = "anonymous";
  baseSnapshot.src = `/api/cameras/${activeCamera}/snapshot.jpg?t=${Date.now()}`;
  baseSnapshot.onload = () => {
    redrawCanvas();
    zoneModal.style.display = "flex";
  };
  baseSnapshot.onerror = () => {
    redrawCanvas();
    zoneModal.style.display = "flex";
  };
}

btnOpenZoneDrawer.addEventListener("click", () => openZoneDrawer(false));
if (btnOpenPrivacyDrawer) {
  btnOpenPrivacyDrawer.addEventListener("click", () => openZoneDrawer(true));
}

function redrawCanvas() {
  ctx.clearRect(0, 0, zoneCanvas.width, zoneCanvas.height);

  // 1. Draw base snapshot if available
  if (baseSnapshot.complete && baseSnapshot.naturalWidth > 0) {
    ctx.drawImage(baseSnapshot, 0, 0, zoneCanvas.width, zoneCanvas.height);
  } else {
    ctx.fillStyle = "#222220";
    ctx.fillRect(0, 0, zoneCanvas.width, zoneCanvas.height);
  }

  if (zonePoints.length === 0) return;

  const isPrivacy = zoneTypeSelect && zoneTypeSelect.value === "privacy_mask";

  // 2. Draw polygon lines and filled area
  ctx.beginPath();
  ctx.moveTo(zonePoints[0].x, zonePoints[0].y);
  for (let i = 1; i < zonePoints.length; i++) {
    ctx.lineTo(zonePoints[i].x, zonePoints[i].y);
  }

  if (zonePoints.length >= 3) {
    ctx.closePath();
    ctx.fillStyle = isPrivacy ? "rgba(2, 132, 199, 0.4)" : "rgba(15, 110, 86, 0.35)";
    ctx.fill();
  }

  ctx.strokeStyle = isPrivacy ? "#38bdf8" : "#5DCAA5";
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // 3. Draw vertices
  zonePoints.forEach((pt, idx) => {
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = idx === 0 ? "#BA7517" : (isPrivacy ? "#38bdf8" : "#5DCAA5");
    ctx.fill();
    ctx.strokeStyle = "#FFFFFF";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
}

zoneCanvas.addEventListener("click", (e) => {
  const rect = zoneCanvas.getBoundingClientRect();
  const scaleX = zoneCanvas.width / rect.width;
  const scaleY = zoneCanvas.height / rect.height;

  const x = (e.clientX - rect.left) * scaleX;
  const y = (e.clientY - rect.top) * scaleY;

  zonePoints.push({ x, y });
  redrawCanvas();
});

btnClearZone.addEventListener("click", () => {
  zonePoints = [];
  redrawCanvas();
});

function closeZoneModal() {
  zoneModal.style.display = "none";
  zonePoints = [];
}

btnCloseZoneModal.addEventListener("click", closeZoneModal);
zoneModal.addEventListener("click", (e) => {
  if (e.target === zoneModal) closeZoneModal();
});

btnSaveZone.addEventListener("click", async () => {
  if (zonePoints.length < 3) {
    alert("Please click at least 3 points to form a polygon zone.");
    return;
  }

  const normPoints = zonePoints.map(p => [
    Number((p.x / zoneCanvas.width).toFixed(3)),
    Number((p.y / zoneCanvas.height).toFixed(3))
  ]);

  const zoneType = zoneTypeSelect ? zoneTypeSelect.value : "restricted_zone";

  const payload = {
    name: zoneNameInput.value.trim() || `${activeCamera}_zone`,
    points: normPoints,
    zone_type: zoneType,
    weight: parseInt(zoneWeightInput.value, 10) || 20,
    schedule_mode: zoneScheduleSelect.value,
    description: `${zoneType} on ${activeCamera}`
  };

  try {
    const res = await fetch(`/api/cameras/${activeCamera}/zones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      alert(`✅ ${zoneType === 'privacy_mask' ? 'Privacy Mask' : 'Threat Zone'} [${payload.name}] successfully saved and hot-reloaded into edge pipeline!`);
      closeZoneModal();
    } else {
      const err = await res.json();
      alert(`Error saving zone: ${err.detail || 'Failed'}`);
    }
  } catch (err) {
    alert(`Network error saving zone: ${err.message}`);
  }
});

// Poll intervals
setInterval(fetchStatus, 3000);
setInterval(fetchEvents, 4000);
setInterval(fetchTelemetry, 3000);

fetchStatus();
fetchEvents();
fetchTelemetry();

