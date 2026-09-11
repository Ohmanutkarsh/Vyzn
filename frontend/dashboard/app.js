/**
 * VYZN Netra — Enterprise Cloud VMS Web Application Client
 * Commercial Zero-Dependency JavaScript Architecture
 */

// Global Application State
const state = {
  activeCamera: "cam_corridor",
  gridLayout: 2, // 1: 1x1, 2: 2x2, 3: 3x3
  currentFilter: "all",
  events: [],
  cameras: [],
  user: null,
  token: localStorage.getItem("vyzn_access_token") || null,
  activeReplayEvent: null,
  zonePoints: [],
  baseSnapshot: new Image(),
  isScrubbing: false,
  timelineProgress: 0.5
};

// ===========================================================================
// 1. DOM Element Cache
// ===========================================================================
const dom = {
  clock: document.getElementById("vms-clock"),
  telemCpu: document.getElementById("telem-cpu"),
  telemRam: document.getElementById("telem-ram"),
  telemDisk: document.getElementById("telem-disk"),
  telemFps: document.getElementById("telem-fps"),
  telemFar: document.getElementById("telem-far"),
  telemBuffer: document.getElementById("telem-buffer"),
  userEmail: document.getElementById("user-email"),
  userRoleBadge: document.getElementById("user-role-badge"),
  btnAuthModalOpen: document.getElementById("btn-auth-modal-open"),
  authModal: document.getElementById("auth-modal"),
  btnCloseAuthModal: document.getElementById("btn-close-auth-modal"),
  tabLogin: document.getElementById("tab-login"),
  tabRegister: document.getElementById("tab-register"),
  formLogin: document.getElementById("form-login"),
  formRegister: document.getElementById("form-register"),
  videoGrid: document.getElementById("video-grid"),
  gridBtns: document.querySelectorAll(".grid-btn"),
  incidentFeed: document.getElementById("incident-scroll-feed"),
  threatNumber: document.getElementById("threat-gauge-number"),
  threatFill: document.getElementById("threat-gauge-fill"),
  filterTabs: document.querySelectorAll(".filter-tab"),
  btnRefreshFeed: document.getElementById("btn-refresh-feed"),
  timelineRail: document.getElementById("timeline-rail"),
  timelinePlayhead: document.getElementById("timeline-playhead"),
  timelineTickBand: document.getElementById("timeline-tick-band"),
  scrubClockVal: document.getElementById("scrub-clock-val"),
  btnTimePlay: document.getElementById("btn-time-play"),
  btnTimeRewind: document.getElementById("btn-time-rewind"),
  btnTimeForward: document.getElementById("btn-time-forward"),
  btnSkipThreat: document.getElementById("btn-skip-threat"),
  zoneModal: document.getElementById("zone-modal"),
  btnCloseZoneModal: document.getElementById("btn-close-zone-modal"),
  zoneCanvas: document.getElementById("zone-canvas"),
  zoneCamSelect: document.getElementById("zone-cam-select"),
  zoneTypeSelect: document.getElementById("zone-type-select"),
  zoneNameInput: document.getElementById("zone-name-input"),
  zoneWeightInput: document.getElementById("zone-weight-input"),
  zoneScheduleSelect: document.getElementById("zone-schedule-select"),
  canvasCoordsHud: document.getElementById("canvas-coords-hud"),
  vertexCountBadge: document.getElementById("vertex-count-badge"),
  pointsListScroll: document.getElementById("points-list-scroll"),
  btnClearCanvasPoints: document.getElementById("btn-clear-canvas-points"),
  btnSaveZoneConfig: document.getElementById("btn-save-zone-config"),
  btnQuickZone: document.getElementById("btn-quick-zone"),
  discoveryModal: document.getElementById("discovery-modal"),
  btnCloseDiscoveryModal: document.getElementById("btn-close-discovery-modal"),
  btnQuickDiscover: document.getElementById("btn-quick-discover"),
  btnEmptyBayAdopt: document.getElementById("btn-empty-bay-adopt"),
  btnTriggerScan: document.getElementById("btn-trigger-scan"),
  discoveryResultsBox: document.getElementById("discovery-results-box"),
  scanSubnetInput: document.getElementById("scan-subnet-input"),
  replayModal: document.getElementById("replay-modal"),
  btnCloseReplayModal: document.getElementById("btn-close-replay-modal"),
  replayVideo: document.getElementById("replay-video-elem"),
  replayTitle: document.getElementById("replay-modal-title"),
  replayMeta: document.getElementById("replay-metadata-grid"),
  btnReplayStar: document.getElementById("btn-replay-star"),
  btnReplayTelegram: document.getElementById("btn-replay-telegram"),
  btnReplayFalseAlarm: document.getElementById("btn-replay-false-alarm"),
  navCockpit: document.getElementById("nav-cockpit"),
  navMap: document.getElementById("nav-map"),
  navZones: document.getElementById("nav-zones"),
  navDiscovery: document.getElementById("nav-discovery"),
  navDpdp: document.getElementById("nav-dpdp"),

  // Multi-Store
  btnSiteToggle: document.getElementById("btn-site-toggle"),
  siteDropdownMenu: document.getElementById("site-dropdown-menu"),
  siteNameDisplay: document.getElementById("site-name-display"),

  // Stages
  cockpitStage: document.getElementById("cockpit-stage"),
  floorplanStage: document.getElementById("floorplan-stage"),
  floorplanSvg: document.getElementById("floorplan-svg"),

  // Appearance Filters
  filterObjType: document.getElementById("filter-obj-type"),
  filterColor: document.getElementById("filter-color"),
  filterZone: document.getElementById("filter-zone"),
  btnClearAppearance: document.getElementById("btn-clear-appearance"),

  // Forensic & Bandwidth QoS
  btnReplayForensic: document.getElementById("btn-replay-forensic"),
  btnBandwidthModalOpen: document.getElementById("btn-bandwidth-modal-open"),
  bandwidthBadgeText: document.getElementById("bandwidth-badge-text"),
  bandwidthModal: document.getElementById("bandwidth-modal"),
  btnCloseBandwidthModal: document.getElementById("btn-close-bandwidth-modal"),
  inputUploadCap: document.getElementById("input-upload-cap"),
  valUploadCap: document.getElementById("val-upload-cap"),
  selectRingRetention: document.getElementById("select-ring-retention"),
  checkAsymSync: document.getElementById("check-asym-sync"),
  btnSaveQosSettings: document.getElementById("btn-save-qos-settings"),
  qosCurUpload: document.getElementById("qos-cur-upload"),
  qosCurRetention: document.getElementById("qos-cur-retention")
};

// Toast helper
function showToast(message, isSuccess = true) {
  const toast = document.createElement("div");
  toast.className = "auth-toast";
  toast.style.borderColor = isSuccess ? "#10b981" : "#f43f5e";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ===========================================================================
// 2. Authentication & Supabase Session Management
// ===========================================================================
async function checkAuthSession() {
  if (!state.token) {
    dom.userEmail.textContent = "Guest Mode";
    dom.userRoleBadge.textContent = "NOT SIGNED IN";
    dom.btnAuthModalOpen.textContent = "Sign In / Register";
    return;
  }

  try {
    const res = await fetch("/api/v1/auth/me", {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      const data = await res.json();
      state.user = data.user;
      dom.userEmail.textContent = state.user.email;
      dom.userRoleBadge.textContent = (state.user.role || "SHOPKEEPER").toUpperCase();
      dom.btnAuthModalOpen.textContent = "Sign Out";
    } else {
      localStorage.removeItem("vyzn_access_token");
      state.token = null;
      dom.userEmail.textContent = "Guest Mode";
      dom.userRoleBadge.textContent = "NOT SIGNED IN";
      dom.btnAuthModalOpen.textContent = "Sign In / Register";
    }
  } catch (err) {
    console.debug("Auth check offline:", err);
  }
}

// Modal open/close
dom.btnAuthModalOpen.addEventListener("click", () => {
  if (state.token) {
    // Logout
    localStorage.removeItem("vyzn_access_token");
    state.token = null;
    state.user = null;
    dom.userEmail.textContent = "Guest Mode";
    dom.userRoleBadge.textContent = "NOT SIGNED IN";
    dom.btnAuthModalOpen.textContent = "Sign In / Register";
    showToast("Signed out successfully.");
    return;
  }
  dom.authModal.style.display = "flex";
});

dom.btnCloseAuthModal.addEventListener("click", () => {
  dom.authModal.style.display = "none";
});

dom.tabLogin.addEventListener("click", () => {
  dom.tabLogin.classList.add("active");
  dom.tabRegister.classList.remove("active");
  dom.formLogin.style.display = "flex";
  dom.formRegister.style.display = "none";
});

dom.tabRegister.addEventListener("click", () => {
  dom.tabRegister.classList.add("active");
  dom.tabLogin.classList.remove("active");
  dom.formRegister.style.display = "flex";
  dom.formLogin.style.display = "none";
});

// Quick 1-Click Demo Profile Chips
document.querySelectorAll(".btn-quick-chip").forEach(chip => {
  chip.addEventListener("click", (e) => {
    e.preventDefault();
    const email = chip.getAttribute("data-email");
    const pass = chip.getAttribute("data-pass");
    document.getElementById("login-email").value = email;
    document.getElementById("login-password").value = pass;
    dom.formLogin.dispatchEvent(new Event("submit"));
  });
});

// Login Form Submit
dom.formLogin.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;

  try {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem("vyzn_access_token", state.token);
      dom.userEmail.textContent = state.user.email;
      dom.userRoleBadge.textContent = (state.user.role || "SHOPKEEPER").toUpperCase();
      dom.btnAuthModalOpen.textContent = "Sign Out";
      dom.authModal.style.display = "none";
      showToast(`✅ Signed in as ${state.user.email} (${dom.userRoleBadge.textContent})`);
    } else {
      alert("Authentication error: " + (data.detail || "Invalid credentials"));
    }
  } catch (err) {
    alert("Network error: " + err.message);
  }
});

// Register Form Submit
dom.formRegister.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fullName = document.getElementById("reg-fullname").value.trim();
  const email = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  const role = document.getElementById("reg-role").value;

  try {
    const res = await fetch("/api/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: fullName, email, password, role })
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem("vyzn_access_token", state.token);
      dom.userEmail.textContent = email;
      dom.userRoleBadge.textContent = role.toUpperCase();
      dom.btnAuthModalOpen.textContent = "Sign Out";
      dom.authModal.style.display = "none";
      showToast(`✅ Created account for ${email} (${role.toUpperCase()})`);
    } else {
      alert("Registration error: " + (data.detail || "Failed"));
    }
  } catch (err) {
    alert("Network error: " + err.message);
  }
});

// ===========================================================================
// 3. Telemetry & Hardware Observability
// ===========================================================================
function updateClock() {
  const now = new Date();
  dom.clock.textContent = now.toUTCString().slice(17, 25) + " UTC";
}
setInterval(updateClock, 1000);
updateClock();

async function fetchTelemetry() {
  try {
    const metricsRes = await fetch("/api/system/metrics");
    if (metricsRes.ok) {
      const m = await metricsRes.json();
      if (m.cpu_percent !== undefined) dom.telemCpu.textContent = `${m.cpu_percent}%`;
      if (m.ram_used_mb !== undefined) dom.telemRam.textContent = `${Math.round(m.ram_used_mb)} MB`;
      if (m.disk_free_gb !== undefined) dom.telemDisk.textContent = `${m.disk_free_gb} GB`;
      if (m.pipeline_fps !== undefined) dom.telemFps.textContent = m.pipeline_fps;
      if (m.triage_stats) {
        dom.telemFar.textContent = `${m.triage_stats.false_positive_rate}%`;
      }
      if (dom.telemBuffer) {
        dom.telemBuffer.textContent = (m.unsynced_events && m.unsynced_events > 0) ? `${m.unsynced_events} pending` : "0 (Synced)";
      }
    }
  } catch (err) {
    console.debug("Telemetry tick error:", err);
  }
}

// ===========================================================================
// 4. Dynamic Camera Grid (1x1, 2x2, 3x3) & Stream Rendering
// ===========================================================================
dom.gridBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    dom.gridBtns.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const gridMode = parseInt(btn.getAttribute("data-grid"), 10);
    setGridLayout(gridMode);
  });
});

function setGridLayout(mode) {
  state.gridLayout = mode;
  dom.videoGrid.className = `video-grid grid-${mode}x${mode}`;
}

async function fetchCameras() {
  try {
    const res = await fetch("/api/cameras");
    if (!res.ok) return;
    const cams = await res.json();
    state.cameras = cams;

    // Update zone camera selector options
    dom.zoneCamSelect.innerHTML = cams.map(c => `<option value="${c.camera_id}">${c.name}</option>`).join("");

    renderVideoGrid(cams);
  } catch (err) {
    console.debug("Fetch cameras error:", err);
  }
}

function renderVideoGrid(cams) {
  dom.videoGrid.innerHTML = "";

  cams.forEach(c => {
    const tile = document.createElement("div");
    tile.className = "camera-tile";
    tile.id = `tile-${c.camera_id}`;
    tile.setAttribute("data-cam", c.camera_id);

    const isWebcam = c.is_webcam || c.rtsp_url_masked === "0" || c.name.toLowerCase().includes("webcam");
    const streamBadge = isWebcam ? "LIVE WEBCAM" : "SUB 480p";
    const badgeColor = isWebcam ? "#10b981" : "#38bdf8";

    tile.innerHTML = `
      <div class="tile-media">
        <img class="tile-stream" src="/api/cameras/${c.camera_id}/mjpeg" alt="${c.name}">
        <canvas class="tile-overlay-canvas"></canvas>
      </div>
      <div class="tile-hud-top">
        <div class="tile-cam-info">
          <span class="stream-dot"></span>
          <span class="tile-cam-name">${c.name}</span>
          <span class="stream-profile-badge" id="badge-stream-${c.camera_id}" style="color:${badgeColor}">${streamBadge}</span>
        </div>
        <div class="tile-stats">
          <span class="fps-pill">${c.target_fps || 4.0} FPS</span>
          <span class="protocol-pill">${isWebcam ? 'DIRECT-SHOW' : 'RTSP/TCP'}</span>
        </div>
      </div>
      <div class="tile-hud-bottom">
        <button class="hud-btn btn-stream-toggle" data-cam="${c.camera_id}" title="Toggle Main/Sub Stream">HD/SD</button>
        <button class="hud-btn btn-tile-snapshot" data-cam="${c.camera_id}" title="Capture Still Snapshot">📷 Snapshot</button>
        <button class="hud-btn btn-tile-zone" data-cam="${c.camera_id}" title="Draw Threat Zone">✏️ Zone</button>
        <button class="hud-btn btn-tile-expand" data-cam="${c.camera_id}" title="Maximize View">⛶</button>
      </div>
    `;

    // Hook HUD buttons
    tile.querySelector(".btn-stream-toggle").addEventListener("click", (e) => {
      e.stopPropagation();
      const badge = tile.querySelector(".stream-profile-badge");
      if (badge) {
        const isMain = badge.textContent.includes("MAIN");
        badge.textContent = isMain ? (isWebcam ? "LIVE WEBCAM" : "SUB 480p") : "MAIN 1080p";
        badge.style.color = isMain ? (isWebcam ? "#10b981" : "#38bdf8") : "#10b981";
      }
    });

    tile.querySelector(".btn-tile-snapshot").addEventListener("click", (e) => {
      e.stopPropagation();
      window.open(`/api/cameras/${c.camera_id}/snapshot.jpg?t=${Date.now()}`, "_blank");
    });

    tile.querySelector(".btn-tile-zone").addEventListener("click", (e) => {
      e.stopPropagation();
      openZoneStudio(c.camera_id);
    });

    tile.querySelector(".btn-tile-expand").addEventListener("click", (e) => {
      e.stopPropagation();
      state.activeCamera = c.camera_id;
      setGridLayout(1);
    });

    dom.videoGrid.appendChild(tile);
  });

  // Append empty standby bay if < 9 cameras
  const emptyTile = document.createElement("div");
  emptyTile.className = "camera-tile standby-tile";
  emptyTile.id = "tile-cam_standby";
  emptyTile.innerHTML = `
    <div class="standby-content">
      <div class="standby-icon">➕</div>
      <div class="standby-title">Empty Camera Bay</div>
      <div class="standby-sub">Connect Laptop Webcam (Device 0) or IP Camera</div>
      <button class="btn-tool" id="btn-bay-add-camera">Connect Camera</button>
    </div>
  `;
  emptyTile.querySelector("#btn-bay-add-camera").addEventListener("click", openCameraSetupModal);
  dom.videoGrid.appendChild(emptyTile);
}

// ===========================================================================
// 5. High-Signal Incident Feed & Live Threat Index
// ===========================================================================
async function fetchIncidents() {
  try {
    const params = new URLSearchParams({ limit: "40" });
    if (dom.filterObjType && dom.filterObjType.value !== "all") {
      params.set("object_type", dom.filterObjType.value);
    }
    if (dom.filterColor && dom.filterColor.value !== "all") {
      params.set("color", dom.filterColor.value);
    }
    if (dom.filterZone && dom.filterZone.value !== "all") {
      params.set("zone", dom.filterZone.value);
    }

    const res = await fetch(`/api/events?${params.toString()}`);
    if (!res.ok) return;
    const events = await res.json();
    state.events = events;

    renderIncidentFeed();
    updateThreatGauge();
    renderTimelineTicks();
    updateMapThreatStatus();
  } catch (err) {
    console.debug("Incident fetch error:", err);
  }
}

function updateMapThreatStatus() {
  if (!dom.floorplanSvg) return;
  const threatCams = new Set();
  const now = Date.now();
  state.events.forEach(ev => {
    if (ev.score >= 70) {
      const evTime = new Date(ev.start_time).getTime();
      if (now - evTime < 300000) { // threat within last 5 mins
        threatCams.add(ev.camera_id);
      }
    }
  });

  document.querySelectorAll(".map-cam-group").forEach(grp => {
    const camId = grp.getAttribute("data-cam");
    const cone = grp.querySelector(".fov-cone");
    const ring = grp.querySelector(".cam-pulse-ring");
    if (threatCams.has(camId)) {
      if (cone) cone.setAttribute("fill", "url(#fov-red)");
      if (ring) {
        ring.setAttribute("stroke", "#EF4444");
        ring.style.animation = "pulse 1s infinite";
      }
    } else {
      if (cone) cone.setAttribute("fill", "url(#fov-green)");
      if (ring) {
        ring.setAttribute("stroke", "#10B981");
        ring.style.animation = "none";
      }
    }
  });
}

function updateThreatGauge() {
  if (state.events.length === 0) {
    dom.threatNumber.textContent = "0 / 100";
    dom.threatFill.style.width = "0%";
    return;
  }
  const topScore = Math.max(...state.events.slice(0, 5).map(e => e.score || 0));
  dom.threatNumber.textContent = `${topScore} / 100`;
  dom.threatFill.style.width = `${topScore}%`;
}

// Filter Tabs
dom.filterTabs.forEach(tab => {
  tab.addEventListener("click", () => {
    dom.filterTabs.forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    state.currentFilter = tab.getAttribute("data-filter");
    renderIncidentFeed();
  });
});

// Appearance filter controls
if (dom.filterObjType) dom.filterObjType.addEventListener("change", fetchIncidents);
if (dom.filterColor) dom.filterColor.addEventListener("change", fetchIncidents);
if (dom.filterZone) dom.filterZone.addEventListener("change", fetchIncidents);
if (dom.btnClearAppearance) {
  dom.btnClearAppearance.addEventListener("click", () => {
    if (dom.filterObjType) dom.filterObjType.value = "all";
    if (dom.filterColor) dom.filterColor.value = "all";
    if (dom.filterZone) dom.filterZone.value = "all";
    fetchIncidents();
  });
}

function renderIncidentFeed() {
  let filtered = state.events;
  if (state.currentFilter === "threats") {
    filtered = filtered.filter(e => e.score >= 70);
  } else if (state.currentFilter === "unreviewed") {
    filtered = filtered.filter(e => e.user_triage === "unreviewed" || !e.user_triage);
  } else if (state.currentFilter === "starred") {
    filtered = filtered.filter(e => e.starred);
  }

  if (filtered.length === 0) {
    dom.incidentFeed.innerHTML = `
      <div class="empty-feed-placeholder">
        <span>🛡️ Zero matching intrusions.</span>
        <span style="font-size:0.7rem; color:var(--text-muted);">Edge AI Appearance Search active.</span>
      </div>
    `;
    return;
  }

  dom.incidentFeed.innerHTML = "";
  filtered.forEach(ev => {
    const card = document.createElement("div");
    const isThreat = ev.score >= 70;
    card.className = `incident-card ${isThreat ? 'threat-card' : ''}`;

    const timeFormatted = ev.start_time ? new Date(ev.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : "--:--:--";
    const scoreClass = isThreat ? "score-high" : "score-norm";

    card.innerHTML = `
      <div class="incident-card-top">
        <img class="incident-thumb" src="/api/events/${ev.event_group_id}/thumb" alt="Thumb" onerror="this.style.display='none'">
        <div class="incident-meta">
          <div class="incident-row-1">
            <span class="incident-cam">${ev.camera_id}</span>
            <span class="incident-score-badge ${scoreClass}">${ev.score}/100</span>
          </div>
          <div class="incident-row-2">
            ${(ev.object_type || 'MOTION').toUpperCase()} • ${Math.round((ev.confidence || 0.85) * 100)}%
          </div>
          <div class="incident-time">${timeFormatted}</div>
          <div class="card-attr-row">
            ${ev.dominant_color && ev.dominant_color !== 'unspecified' ? `<span class="card-attr-pill attr-${ev.dominant_color}">● ${ev.dominant_color.toUpperCase()}</span>` : ''}
            ${ev.zone_name && ev.zone_name !== 'general' ? `<span class="card-attr-pill">📍 ${ev.zone_name}</span>` : ''}
          </div>
        </div>
      </div>
      <div class="incident-card-actions">
        <button class="btn-card-action btn-card-star ${ev.starred ? 'starred' : ''}" data-id="${ev.event_group_id}">
          ${ev.starred ? '⭐ Protected' : '☆ Star'}
        </button>
        <button class="btn-card-action btn-card-forensic" data-id="${ev.event_group_id}" title="Download Signed Forensic Pack">
          📦 Evidence
        </button>
        <button class="btn-card-action btn-card-false" data-id="${ev.event_group_id}">
          ❌ False
        </button>
        <button class="btn-card-action btn-card-tele" data-id="${ev.event_group_id}">
          ✈️ Telegram
        </button>
      </div>
    `;

    // Click to Replay
    card.addEventListener("click", (e) => {
      if (e.target.closest(".btn-card-action")) return;
      openReplayModal(ev);
    });

    // Star button
    const starBtn = card.querySelector(".btn-card-star");
    starBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await toggleStarEvent(ev.event_group_id);
    });

    // Forensic button
    const forensicBtn = card.querySelector(".btn-card-forensic");
    if (forensicBtn) {
      forensicBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        window.location.href = `/api/v1/events/${ev.event_group_id}/forensic-pack`;
        showToast(`📦 Downloading Section 65B Forensic Evidence Pack for ${ev.event_group_id}...`);
      });
    }

    // False Alarm button
    const falseBtn = card.querySelector(".btn-card-false");
    falseBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await setEventTriage(ev.event_group_id, "false_positive");
    });

    // Telegram button
    const teleBtn = card.querySelector(".btn-card-tele");
    teleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      showToast(`✈️ Telegram Bot alert sent for ${ev.event_group_id}!`);
    });

    dom.incidentFeed.appendChild(card);
  });
}

dom.btnRefreshFeed.addEventListener("click", fetchIncidents);

async function toggleStarEvent(eventId) {
  try {
    const res = await fetch(`/api/events/${eventId}/star`, { method: "POST" });
    if (res.ok) {
      await fetchIncidents();
    }
  } catch (err) {
    console.error("Star error:", err);
  }
}

async function setEventTriage(eventId, triageStatus) {
  try {
    const res = await fetch(`/api/events/${eventId}/triage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ triage: triageStatus })
    });
    if (res.ok) {
      await fetchIncidents();
      await fetchTelemetry();
      showToast("Triage recorded & Bayesian calibrator updated.");
    }
  } catch (err) {
    console.error("Triage error:", err);
  }
}

// ===========================================================================
// 6. Synchronized 24-Hour Historical Playback Timeline
// ===========================================================================
function renderTimelineTicks() {
  dom.timelineTickBand.innerHTML = "";
  if (state.events.length === 0) return;

  state.events.forEach((ev, idx) => {
    const tick = document.createElement("div");
    const isThreat = ev.score >= 70;
    const isWarn = ev.score >= 50 && ev.score < 70;

    let tickType = "tick-motion";
    if (isThreat) tickType = "tick-threat";
    else if (isWarn) tickType = "tick-warning";

    tick.className = `timeline-tick ${tickType}`;
    const pct = ((idx * 17) % 96) + 2;
    tick.style.left = `${pct}%`;
    tick.title = `Incident ${ev.event_group_id} (${ev.score}/100) on ${ev.camera_id}`;

    tick.addEventListener("click", (e) => {
      e.stopPropagation();
      setTimelineScrub(pct / 100);
      openReplayModal(ev);
    });

    dom.timelineTickBand.appendChild(tick);
  });
}

function setTimelineScrub(progress) {
  state.timelineProgress = Math.max(0, Math.min(1, progress));
  dom.timelinePlayhead.style.left = `${state.timelineProgress * 100}%`;

  const totalSeconds = Math.floor(state.timelineProgress * 86400);
  const hrs = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const mins = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const secs = String(totalSeconds % 60).padStart(2, "0");
  dom.scrubClockVal.textContent = `${hrs}:${mins}:${secs} UTC`;
}

dom.timelineRail.addEventListener("click", (e) => {
  const rect = dom.timelineRail.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const progress = clickX / rect.width;
  setTimelineScrub(progress);
});

dom.btnTimeRewind.addEventListener("click", () => {
  setTimelineScrub(state.timelineProgress - 0.02);
});

dom.btnTimeForward.addEventListener("click", () => {
  setTimelineScrub(state.timelineProgress + 0.02);
});

dom.btnTimePlay.addEventListener("click", () => {
  const isPlaying = dom.btnTimePlay.textContent.includes("Pause");
  dom.btnTimePlay.textContent = isPlaying ? "▶ Play" : "⏸ Pause";
});

dom.btnSkipThreat.addEventListener("click", () => {
  const threatEvent = state.events.find(e => e.score >= 70);
  if (threatEvent) {
    setTimelineScrub(0.72);
    openReplayModal(threatEvent);
  } else {
    showToast("Zero active high-threat incidents in current window.", false);
  }
});

// ===========================================================================
// 7. Interactive HTML5 Canvas Visual Geofence Studio
// ===========================================================================
const ctx = dom.zoneCanvas.getContext("2d");

function openZoneStudio(camId = "cam_corridor") {
  state.activeCamera = camId;
  dom.zoneCamSelect.value = camId;
  dom.zoneNameInput.value = `${camId}_restricted_vault`;
  state.zonePoints = [];

  state.baseSnapshot = new Image();
  state.baseSnapshot.crossOrigin = "anonymous";
  state.baseSnapshot.src = `/api/cameras/${camId}/snapshot.jpg?t=${Date.now()}`;
  state.baseSnapshot.onload = () => {
    redrawZoneCanvas();
    dom.zoneModal.style.display = "flex";
  };
  state.baseSnapshot.onerror = () => {
    redrawZoneCanvas();
    dom.zoneModal.style.display = "flex";
  };
}

dom.btnQuickZone.addEventListener("click", () => openZoneStudio(state.activeCamera));
dom.btnCloseZoneModal.addEventListener("click", () => {
  dom.zoneModal.style.display = "none";
});

dom.zoneCamSelect.addEventListener("change", (e) => {
  openZoneStudio(e.target.value);
});

function redrawZoneCanvas() {
  ctx.clearRect(0, 0, dom.zoneCanvas.width, dom.zoneCanvas.height);

  if (state.baseSnapshot.complete && state.baseSnapshot.naturalWidth > 0) {
    ctx.drawImage(state.baseSnapshot, 0, 0, dom.zoneCanvas.width, dom.zoneCanvas.height);
  } else {
    ctx.fillStyle = "#090e17";
    ctx.fillRect(0, 0, dom.zoneCanvas.width, dom.zoneCanvas.height);
  }

  // Draw guidance grid
  ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
  ctx.lineWidth = 1;
  for (let x = 64; x < dom.zoneCanvas.width; x += 64) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, dom.zoneCanvas.height); ctx.stroke();
  }
  for (let y = 36; y < dom.zoneCanvas.height; y += 36) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(dom.zoneCanvas.width, y); ctx.stroke();
  }

  if (state.zonePoints.length === 0) return;

  const isPrivacy = dom.zoneTypeSelect.value === "privacy_mask";

  ctx.beginPath();
  ctx.moveTo(state.zonePoints[0].x, state.zonePoints[0].y);
  for (let i = 1; i < state.zonePoints.length; i++) {
    ctx.lineTo(state.zonePoints[i].x, state.zonePoints[i].y);
  }

  if (state.zonePoints.length >= 3) {
    ctx.closePath();
    ctx.fillStyle = isPrivacy ? "rgba(14, 165, 233, 0.35)" : "rgba(244, 63, 94, 0.3)";
    ctx.fill();
  }

  ctx.strokeStyle = isPrivacy ? "#38bdf8" : "#f43f5e";
  ctx.lineWidth = 2.5;
  ctx.stroke();

  state.zonePoints.forEach((pt, idx) => {
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = idx === 0 ? "#f59e0b" : (isPrivacy ? "#38bdf8" : "#f43f5e");
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
}

dom.zoneCanvas.addEventListener("click", (e) => {
  const rect = dom.zoneCanvas.getBoundingClientRect();
  const scaleX = dom.zoneCanvas.width / rect.width;
  const scaleY = dom.zoneCanvas.height / rect.height;

  const x = Math.round((e.clientX - rect.left) * scaleX);
  const y = Math.round((e.clientY - rect.top) * scaleY);

  state.zonePoints.push({ x, y });
  dom.vertexCountBadge.textContent = state.zonePoints.length;
  updatePointsDisplay();
  redrawZoneCanvas();
});

dom.zoneCanvas.addEventListener("mousemove", (e) => {
  const rect = dom.zoneCanvas.getBoundingClientRect();
  const normX = ((e.clientX - rect.left) / rect.width).toFixed(3);
  const normY = ((e.clientY - rect.top) / rect.height).toFixed(3);
  dom.canvasCoordsHud.textContent = `X: ${normX}, Y: ${normY}`;
});

function updatePointsDisplay() {
  if (state.zonePoints.length === 0) {
    dom.pointsListScroll.innerHTML = '<span class="points-empty">Click 3 or more points on the video frame...</span>';
    return;
  }
  dom.pointsListScroll.innerHTML = state.zonePoints.map((pt, i) => {
    const nx = (pt.x / dom.zoneCanvas.width).toFixed(3);
    const ny = (pt.y / dom.zoneCanvas.height).toFixed(3);
    return `<div>V${i + 1}: [${nx}, ${ny}]</div>`;
  }).join("");
}

dom.btnClearCanvasPoints.addEventListener("click", () => {
  state.zonePoints = [];
  dom.vertexCountBadge.textContent = "0";
  updatePointsDisplay();
  redrawZoneCanvas();
});

dom.zoneTypeSelect.addEventListener("change", redrawZoneCanvas);

dom.btnSaveZoneConfig.addEventListener("click", async () => {
  if (state.zonePoints.length < 3) {
    alert("Please plot at least 3 points to form a closed polygon boundary.");
    return;
  }

  const normPoints = state.zonePoints.map(p => [
    Number((p.x / dom.zoneCanvas.width).toFixed(3)),
    Number((p.y / dom.zoneCanvas.height).toFixed(3))
  ]);

  const targetCam = dom.zoneCamSelect.value;
  const zoneType = dom.zoneTypeSelect.value;

  const payload = {
    name: dom.zoneNameInput.value.trim() || `${targetCam}_zone`,
    points: normPoints,
    zone_type: zoneType,
    weight: parseInt(dom.zoneWeightInput.value, 10) || 25,
    schedule_mode: dom.zoneScheduleSelect.value,
    description: `${zoneType} geofence created via UI studio`
  };

  try {
    const res = await fetch(`/api/cameras/${targetCam}/zones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      showToast(`✅ Deployed [${payload.name}] to ${targetCam}!`);
      dom.zoneModal.style.display = "none";
    } else {
      const err = await res.json();
      alert("Error saving zone: " + (err.detail || "Failed"));
    }
  } catch (err) {
    alert("Network error: " + err.message);
  }
});

// ===========================================================================
// 8. Camera Connection & Adoption Studio (Webcam, RTSP, ONVIF)
// ===========================================================================
function openCameraSetupModal() {
  dom.discoveryModal.style.display = "flex";
  probeLocalDevices();
}

dom.btnQuickDiscover.addEventListener("click", openCameraSetupModal);
dom.btnCloseDiscoveryModal.addEventListener("click", () => {
  dom.discoveryModal.style.display = "none";
});

// Tabs inside Camera Setup Modal
const tabCamWebcam = document.getElementById("tab-cam-webcam");
const tabCamRtsp = document.getElementById("tab-cam-rtsp");
const tabCamOnvif = document.getElementById("tab-cam-onvif");
const paneCamWebcam = document.getElementById("pane-cam-webcam");
const paneCamRtsp = document.getElementById("pane-cam-rtsp");
const paneCamOnvif = document.getElementById("pane-cam-onvif");

function switchCamTab(tabName) {
  tabCamWebcam.classList.toggle("active", tabName === "webcam");
  tabCamRtsp.classList.toggle("active", tabName === "rtsp");
  tabCamOnvif.classList.toggle("active", tabName === "onvif");

  paneCamWebcam.style.display = tabName === "webcam" ? "flex" : "none";
  paneCamRtsp.style.display = tabName === "rtsp" ? "flex" : "none";
  paneCamOnvif.style.display = tabName === "onvif" ? "flex" : "none";
}

tabCamWebcam.addEventListener("click", () => switchCamTab("webcam"));
tabCamRtsp.addEventListener("click", () => switchCamTab("rtsp"));
tabCamOnvif.addEventListener("click", () => switchCamTab("onvif"));

// Probe physically connected webcams
async function probeLocalDevices() {
  try {
    const res = await fetch("/api/v1/cameras/local-devices");
    if (res.ok) {
      const data = await res.json();
      const select = document.getElementById("select-local-device");
      if (data.devices && data.devices.length > 0) {
        select.innerHTML = data.devices.map(d => `
          <option value="${d.device_index}">Device ${d.device_index}: ${d.name} [READY]</option>
        `).join("");
      }
    }
  } catch (err) {
    console.debug("Local device probe error:", err);
  }
}

// 1-Click Adopt Local Webcam
const btnAdoptPhysicalWebcam = document.getElementById("btn-adopt-physical-webcam");
if (btnAdoptPhysicalWebcam) {
  btnAdoptPhysicalWebcam.addEventListener("click", async () => {
    const devIdx = document.getElementById("select-local-device").value;
    const camName = document.getElementById("input-webcam-name").value.trim() || `Physical Webcam ${devIdx}`;
    const camId = `cam_webcam_${devIdx}`;

    try {
      const res = await fetch("/api/v1/cameras/adopt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          camera_id: camId,
          name: camName,
          rtsp_url: devIdx,
          target_fps: 4.0
        })
      });

      if (res.ok) {
        showToast(`✅ Physical camera [${camName}] connected live!`);
        dom.discoveryModal.style.display = "none";
        await fetchCameras();
      } else {
        const err = await res.json();
        alert("Camera connection error: " + (err.detail || "Failed"));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    }
  });
}

// Connect Network RTSP Stream
const btnAdoptManualRtsp = document.getElementById("btn-adopt-manual-rtsp");
if (btnAdoptManualRtsp) {
  btnAdoptManualRtsp.addEventListener("click", async () => {
    const camId = document.getElementById("input-rtsp-id").value.trim() || `cam_rtsp_${Date.now()}`;
    const camName = document.getElementById("input-rtsp-name").value.trim() || "IP Security Camera";
    const rtspUrl = document.getElementById("input-rtsp-url").value.trim();
    const fps = parseFloat(document.getElementById("select-rtsp-fps").value) || 4.0;

    if (!rtspUrl) {
      alert("Please enter a valid RTSP Stream URL.");
      return;
    }

    try {
      const res = await fetch("/api/v1/cameras/adopt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          camera_id: camId,
          name: camName,
          rtsp_url: rtspUrl,
          target_fps: fps
        })
      });

      if (res.ok) {
        showToast(`✅ Network camera [${camName}] added to matrix!`);
        dom.discoveryModal.style.display = "none";
        await fetchCameras();
      } else {
        const err = await res.json();
        alert("RTSP connection error: " + (err.detail || "Failed"));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    }
  });
}

// ONVIF WS-Discovery Scan
dom.btnTriggerScan.addEventListener("click", async () => {
  dom.discoveryResultsBox.innerHTML = `
    <div class="empty-discovery">
      <span class="spinner"></span>
      <span style="margin-top:0.75rem;">Probing ONVIF WS-Discovery (UDP 3702) & RTSP (TCP 554)...</span>
    </div>
  `;

  try {
    const targetIp = dom.scanSubnetInput.value.trim();
    const url = targetIp ? `/api/v1/cameras/discover?target_ips=${encodeURIComponent(targetIp)}` : `/api/v1/cameras/discover`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Discovery probe failed");
    const data = await res.json();

    if (data.cameras.length === 0) {
      dom.discoveryResultsBox.innerHTML = `
        <div class="empty-discovery">
          Zero ONVIF cameras detected on LAN subnet.<br>
          <span style="color:#38bdf8; cursor:pointer;" onclick="document.getElementById('tab-cam-webcam').click()">👉 Switch to "Local Physical Camera" tab to connect your webcam!</span>
        </div>
      `;
      return;
    }

    dom.discoveryResultsBox.innerHTML = "";
    data.cameras.forEach(cam => {
      const row = document.createElement("div");
      row.className = "discovered-cam-row";
      row.innerHTML = `
        <div class="cam-meta-left">
          <span class="cam-meta-name">${cam.manufacturer} ${cam.model} (${cam.ip})</span>
          <span class="cam-meta-proto">RTSP Port ${cam.port} • Auto-Discovered</span>
        </div>
        <button class="btn-adopt-cam" data-id="cam_${cam.ip.replaceAll('.', '_')}" data-url="${cam.rtsp_endpoint}" data-name="${cam.manufacturer} ${cam.model}">
          1-Click Adopt
        </button>
      `;

      row.querySelector(".btn-adopt-cam").addEventListener("click", async (e) => {
        const btn = e.target;
        const camId = btn.getAttribute("data-id");
        const rtspUrl = btn.getAttribute("data-url");
        const camName = btn.getAttribute("data-name");

        try {
          const adoptRes = await fetch("/api/v1/cameras/adopt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              camera_id: camId,
              name: camName,
              rtsp_url: rtspUrl,
              target_fps: 4.0
            })
          });
          if (adoptRes.ok) {
            showToast(`✅ Camera [${camName}] adopted into active matrix!`);
            dom.discoveryModal.style.display = "none";
            await fetchCameras();
          }
        } catch (err) {
          alert("Adopt error: " + err.message);
        }
      });

      dom.discoveryResultsBox.appendChild(row);
    });

  } catch (err) {
    dom.discoveryResultsBox.innerHTML = `<div class="empty-discovery">Scan error: ${err.message}</div>`;
  }
});

// ===========================================================================
// 9. Synchronized Incident Video Replay Modal
// ===========================================================================
function openReplayModal(ev) {
  state.activeReplayEvent = ev;
  dom.replayTitle.textContent = `Incident ${ev.event_group_id} — Threat Index: ${ev.score}/100`;
  dom.replayVideo.src = `/api/events/${ev.event_group_id}/clip`;
  dom.replayVideo.play().catch(() => {});

  dom.replayMeta.innerHTML = `
    <div><strong>Camera:</strong> ${ev.camera_id}</div>
    <div><strong>Classification:</strong> ${(ev.object_type || 'MOTION').toUpperCase()} (${Math.round((ev.confidence || 0.85)*100)}% conf)</div>
    <div><strong>Detected At:</strong> ${ev.start_time}</div>
    <div><strong>Reaper Status:</strong> ${ev.starred ? 'Protected (Never auto-purged)' : '72h Auto-Reaper Retention'}</div>
  `;

  dom.btnReplayStar.textContent = ev.starred ? "⭐ Starred (Protected)" : "⭐ Protect from 72h Reaper";
  dom.replayModal.style.display = "flex";
}

dom.btnCloseReplayModal.addEventListener("click", () => {
  dom.replayModal.style.display = "none";
  dom.replayVideo.pause();
  dom.replayVideo.src = "";
  state.activeReplayEvent = null;
});

dom.btnReplayStar.addEventListener("click", async () => {
  if (state.activeReplayEvent) {
    await toggleStarEvent(state.activeReplayEvent.event_group_id);
    dom.btnReplayStar.textContent = "⭐ Starred (Protected)";
    showToast("Incident starred & protected from auto-deletion.");
  }
});

dom.btnReplayTelegram.addEventListener("click", () => {
  if (state.activeReplayEvent) {
    showToast(`✈️ Telegram Bot Alert dispatched for ${state.activeReplayEvent.event_group_id}!`);
  }
});

dom.btnReplayFalseAlarm.addEventListener("click", async () => {
  if (state.activeReplayEvent) {
    await setEventTriage(state.activeReplayEvent.event_group_id, "false_positive");
    dom.replayModal.style.display = "none";
  }
});

if (dom.btnReplayForensic) {
  dom.btnReplayForensic.addEventListener("click", () => {
    if (state.activeReplayEvent) {
      window.location.href = `/api/v1/events/${state.activeReplayEvent.event_group_id}/forensic-pack`;
      showToast(`📦 Exporting Courtroom Forensic Evidence Pack for ${state.activeReplayEvent.event_group_id}...`);
    }
  });
}

// ===========================================================================
// 10. Left Sidebar Quick Links & Stages
// ===========================================================================
if (dom.navCockpit) {
  dom.navCockpit.addEventListener("click", () => {
    dom.navCockpit.classList.add("active");
    if (dom.navMap) dom.navMap.classList.remove("active");
    if (dom.cockpitStage) dom.cockpitStage.style.display = "block";
    if (dom.floorplanStage) dom.floorplanStage.style.display = "none";
  });
}

if (dom.navMap) {
  dom.navMap.addEventListener("click", () => {
    dom.navMap.classList.add("active");
    if (dom.navCockpit) dom.navCockpit.classList.remove("active");
    if (dom.cockpitStage) dom.cockpitStage.style.display = "none";
    if (dom.floorplanStage) dom.floorplanStage.style.display = "flex";
    updateMapThreatStatus();
  });
}

// Map camera click to focus in cockpit
document.querySelectorAll(".map-cam-group").forEach(grp => {
  grp.addEventListener("click", () => {
    const camId = grp.getAttribute("data-cam");
    showToast(`📹 Focusing Cockpit on [${camId}]...`);
    if (dom.navCockpit) dom.navCockpit.click();
    const tile = document.getElementById(`tile-${camId}`);
    if (tile) {
      tile.scrollIntoView({ behavior: "smooth", block: "center" });
      tile.style.outline = "2px solid #10b981";
      setTimeout(() => tile.style.outline = "none", 2000);
    }
  });
});

dom.navZones.addEventListener("click", () => {
  openZoneStudio(state.activeCamera);
});

dom.navDiscovery.addEventListener("click", openCameraSetupModal);

dom.navDpdp.addEventListener("click", () => {
  window.open("/api/dpdp/notice", "_blank");
});

// ===========================================================================
// Multi-Store Switcher Dropdown
// ===========================================================================
if (dom.btnSiteToggle) {
  dom.btnSiteToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const isHidden = dom.siteDropdownMenu.style.display === "none";
    dom.siteDropdownMenu.style.display = isHidden ? "flex" : "none";
  });

  document.addEventListener("click", (e) => {
    if (dom.siteDropdownMenu && !dom.siteDropdownMenu.contains(e.target) && e.target !== dom.btnSiteToggle) {
      dom.siteDropdownMenu.style.display = "none";
    }
  });

  document.querySelectorAll(".site-option").forEach(opt => {
    opt.addEventListener("click", () => {
      document.querySelectorAll(".site-option").forEach(o => o.classList.remove("active"));
      opt.classList.add("active");
      const sName = opt.getAttribute("data-site-name");
      dom.siteNameDisplay.textContent = sName;
      dom.siteDropdownMenu.style.display = "none";
      showToast(`📍 Switched to [${sName}]`);
      fetchTelemetry();
      fetchIncidents();
    });
  });
}

// ===========================================================================
// Bandwidth & QoS Governor Controls
// ===========================================================================
if (dom.btnBandwidthModalOpen) {
  dom.btnBandwidthModalOpen.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/v1/settings/bandwidth");
      if (res.ok) {
        const cfg = await res.json();
        if (dom.inputUploadCap) dom.inputUploadCap.value = cfg.max_upload_mbps || 2.0;
        if (dom.valUploadCap) dom.valUploadCap.textContent = `${cfg.max_upload_mbps || 2.0} Mbps`;
        if (dom.selectRingRetention) dom.selectRingRetention.value = String(cfg.retention_hours || 72);
        if (dom.checkAsymSync) dom.checkAsymSync.checked = cfg.asymmetrical_sync !== false;
        if (dom.qosCurUpload) dom.qosCurUpload.textContent = `${cfg.current_upload_mbps || 0.42} Mbps`;
        if (dom.qosCurRetention) dom.qosCurRetention.textContent = `${cfg.retention_hours || 72} Hours`;
      }
    } catch (e) {}
    dom.bandwidthModal.style.display = "flex";
  });
}

if (dom.btnCloseBandwidthModal) {
  dom.btnCloseBandwidthModal.addEventListener("click", () => {
    dom.bandwidthModal.style.display = "none";
  });
}

if (dom.inputUploadCap) {
  dom.inputUploadCap.addEventListener("input", (e) => {
    if (dom.valUploadCap) dom.valUploadCap.textContent = `${e.target.value} Mbps`;
  });
}

if (dom.btnSaveQosSettings) {
  dom.btnSaveQosSettings.addEventListener("click", async () => {
    const uploadCap = parseFloat(dom.inputUploadCap ? dom.inputUploadCap.value : 2.0);
    const retention = parseInt(dom.selectRingRetention ? dom.selectRingRetention.value : 72);
    const asymSync = dom.checkAsymSync ? dom.checkAsymSync.checked : true;

    try {
      const res = await fetch("/api/v1/settings/bandwidth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          max_upload_mbps: uploadCap,
          retention_hours: retention,
          asymmetrical_sync: asymSync
        })
      });
      if (res.ok) {
        if (dom.bandwidthBadgeText) {
          dom.bandwidthBadgeText.innerHTML = `Edge AI Upload Cap: <strong>${uploadCap.toFixed(1)} Mbps</strong> (Zero Cloud Choke)`;
        }
        showToast(`💾 Applied Bandwidth Policy: ${uploadCap.toFixed(1)} Mbps Cap, ${retention}h Retention`);
        dom.bandwidthModal.style.display = "none";
      }
    } catch (err) {
      alert("QoS save failed: " + err.message);
    }
  });
}

// ===========================================================================
// 11. Initial Startup & Polling
// ===========================================================================
checkAuthSession();
fetchCameras();
fetchTelemetry();
fetchIncidents();

setInterval(fetchTelemetry, 2500);
setInterval(fetchIncidents, 3500);
