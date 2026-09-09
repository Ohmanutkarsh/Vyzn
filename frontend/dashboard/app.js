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
        </div>
      `;

      // Click card to open video replay
      card.addEventListener("click", (e) => {
        if (e.target.classList.contains("btn-star-mini")) return;
        openModal(ev);
      });

      // Star button
      const starBtn = card.querySelector(".btn-star-mini");
      starBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleStar(ev.event_group_id, starBtn);
      });

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

// Poll intervals
setInterval(fetchStatus, 3000);
setInterval(fetchEvents, 4000);

fetchStatus();
fetchEvents();
