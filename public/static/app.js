/**
 * VYZN Netra — Enterprise Cloud VMS Web Application Client
 * Commercial Zero-Dependency JavaScript Architecture
 */

// Global Application State
const state = {
  activeCamera: "cam_corridor",
  gridLayout: 2, // 1: 1x1, 2: 2x2, 3: 3x3
  currentFilter: "all",
  currentLocationId: "loc_primary",
  locations: [],
  events: [],
  clipsEvents: [],
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
  userPhonePill: document.getElementById("user-phone-pill"),
  btnPhoneModalOpen: document.getElementById("btn-phone-modal-open"),
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
  navClips: document.getElementById("nav-clips"),
  navSearch: document.getElementById("nav-search"),
  navMap: document.getElementById("nav-map"),
  navZones: document.getElementById("nav-zones"),
  navDiscovery: document.getElementById("nav-discovery"),
  navDpdp: document.getElementById("nav-dpdp"),

  // Dedicated Clips Stage
  clipsStage: document.getElementById("clips-stage"),
  clipsGrid: document.getElementById("clips-grid"),
  clipsFilterTier: document.getElementById("clips-filter-tier"),
  clipsFilterCamera: document.getElementById("clips-filter-camera"),
  btnRefreshClips: document.getElementById("btn-refresh-clips"),

  // Dedicated Search & Investigation Stage (Flow 7)
  searchStage: document.getElementById("search-stage"),
  searchInputQuery: document.getElementById("search-input-query"),
  searchSelectObj: document.getElementById("search-select-obj"),
  searchSelectColor: document.getElementById("search-select-color"),
  searchSelectZone: document.getElementById("search-select-zone"),
  searchSelectCam: document.getElementById("search-select-cam"),
  searchDateFrom: document.getElementById("search-date-from"),
  searchDateTo: document.getElementById("search-date-to"),
  searchSliderScore: document.getElementById("search-slider-score"),
  searchScoreVal: document.getElementById("search-score-val"),
  btnRunSearch: document.getElementById("btn-run-search"),
  btnResetSearch: document.getElementById("btn-reset-search"),
  searchResultsCount: document.getElementById("search-results-count"),
  searchResultsGrid: document.getElementById("search-results-grid"),

  // Multi-Store & Locations
  btnSiteToggle: document.getElementById("btn-site-toggle"),
  siteDropdownMenu: document.getElementById("site-dropdown-menu"),
  siteNameDisplay: document.getElementById("site-name-display"),
  siteOptionsList: document.getElementById("site-options-list"),
  btnOpenAddLocationModal: document.getElementById("btn-open-add-location-modal"),
  locationModal: document.getElementById("location-modal"),
  btnCloseLocationModal: document.getElementById("btn-close-location-modal"),
  formAddLocation: document.getElementById("form-add-location"),
  locNameInput: document.getElementById("loc-name-input"),
  locAddrInput: document.getElementById("loc-addr-input"),

  // Phone OTP Modal
  phoneModal: document.getElementById("phone-modal"),
  btnClosePhoneModal: document.getElementById("btn-close-phone-modal"),
  inputPhoneNumber: document.getElementById("input-phone-number"),
  inputPhoneOtp: document.getElementById("input-phone-otp"),
  btnSendPhoneOtp: document.getElementById("btn-send-phone-otp"),
  btnVerifyPhoneOtp: document.getElementById("btn-verify-phone-otp"),
  phoneStep1: document.getElementById("phone-step-1"),
  phoneStep2: document.getElementById("phone-step-2"),
  phoneFeedback: document.getElementById("phone-feedback"),
  otpHintText: document.getElementById("otp-hint-text"),

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
  qosCurRetention: document.getElementById("qos-cur-retention"),

  // Telegram Alert Center
  btnOpenTelegramModal: document.getElementById("btn-open-telegram-modal"),
  telegramModal: document.getElementById("telegram-modal"),
  btnCloseTelegramModal: document.getElementById("btn-close-telegram-modal"),
  headerTeleDot: document.getElementById("header-tele-dot"),
  headerTeleLabel: document.getElementById("header-tele-label"),
  modalTeleDot: document.getElementById("modal-tele-dot"),
  modalTeleStatusTitle: document.getElementById("modal-tele-status-title"),
  modalTeleStatusDesc: document.getElementById("modal-tele-status-desc"),
  inputTelegramToken: document.getElementById("input-telegram-token"),
  inputTelegramChat: document.getElementById("input-telegram-chat"),
  checkEnablePoller: document.getElementById("check-enable-poller"),
  testPingResult: document.getElementById("test-ping-result"),
  btnTelegramTestPing: document.getElementById("btn-telegram-test-ping"),
  btnSaveTelegramConfig: document.getElementById("btn-save-telegram-config")
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

function showAuthError(message, targetId) {
  // Remove any existing auth errors first
  document.querySelectorAll('.auth-inline-error').forEach(el => el.remove());
  if (!message) return;
  const target = document.getElementById(targetId);
  if (!target) return;
  const err = document.createElement('div');
  err.className = 'auth-inline-error';
  err.textContent = message;
  err.style.cssText = 'color:#ef4444;font-size:0.78rem;margin-top:5px;font-weight:500;';
  target.parentNode.insertBefore(err, target.nextSibling);
  setTimeout(() => err.remove(), 7000);
}

// ===========================================================================
// 2. Authentication & Supabase Session Management
// ===========================================================================
function applyUserToUI(user) {
  if (!user) {
    dom.userEmail.textContent = "Guest Mode";
    dom.userRoleBadge.textContent = "NOT SIGNED IN";
    dom.btnAuthModalOpen.textContent = "Sign In / Register";
    if (dom.userPhonePill) dom.userPhonePill.style.display = "none";
    if (dom.btnPhoneModalOpen) dom.btnPhoneModalOpen.style.display = "none";
    return;
  }
  dom.userEmail.textContent = user.email;
  dom.userRoleBadge.textContent = (user.role || "SHOPKEEPER").toUpperCase();
  dom.btnAuthModalOpen.textContent = "Sign Out";
  if (dom.btnPhoneModalOpen) dom.btnPhoneModalOpen.style.display = "inline-block";

  if (user.phone) {
    if (dom.userPhonePill) {
      dom.userPhonePill.textContent = user.phone_verified ? `✓ ${user.phone}` : `⚠️ ${user.phone}`;
      dom.userPhonePill.title = user.phone_verified ? "Phone number verified via OTP" : "Phone number pending OTP verification";
      dom.userPhonePill.style.color = user.phone_verified ? "#10b981" : "#f59e0b";
      dom.userPhonePill.style.display = "inline-block";
    }
    if (dom.btnPhoneModalOpen) {
      dom.btnPhoneModalOpen.textContent = user.phone_verified ? "📱 Phone Linked" : "📱 Verify OTP";
    }
  } else {
    if (dom.userPhonePill) dom.userPhonePill.style.display = "none";
    if (dom.btnPhoneModalOpen) dom.btnPhoneModalOpen.textContent = "📱 Link Phone";
  }
}

const updateUserUI = applyUserToUI;

async function checkAuthSession() {
  if (!state.token) {
    applyUserToUI(null);
    return;
  }

  try {
    const res = await fetch("/api/v1/auth/me", {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      const data = await res.json();
      state.user = data.user;
      applyUserToUI(state.user);
    } else {
      localStorage.removeItem("vyzn_access_token");
      state.token = null;
      state.user = null;
      applyUserToUI(null);
    }
  } catch (err) {
    console.debug("Auth check offline:", err);
  }
}

// Modal open/close
dom.btnAuthModalOpen.addEventListener("click", async () => {
  if (state.token) {
    // Logout
    localStorage.removeItem("vyzn_access_token");
    state.token = null;
    state.user = null;
    applyUserToUI(null);
    showToast("Signed out successfully.");
    await fetchLocations();
    await fetchCameras();
    await fetchIncidents();
    await fetchClips();
    return;
  }
  dom.authModal.style.display = "flex";
});

dom.btnCloseAuthModal.addEventListener("click", () => {
  dom.authModal.style.display = "none";
});

// Phone OTP Modal Handlers
if (dom.btnPhoneModalOpen) {
  dom.btnPhoneModalOpen.addEventListener("click", () => {
    if (dom.phoneModal) {
      dom.phoneModal.style.display = "flex";
      if (dom.phoneFeedback) dom.phoneFeedback.textContent = "";
      if (state.user && state.user.phone) {
        dom.inputPhoneNumber.value = state.user.phone;
      }
      dom.phoneStep1.style.display = "block";
      dom.phoneStep2.style.display = "none";
    }
  });
}

if (dom.btnClosePhoneModal) {
  dom.btnClosePhoneModal.addEventListener("click", () => {
    if (dom.phoneModal) dom.phoneModal.style.display = "none";
  });
}

if (dom.btnSendPhoneOtp) {
  dom.btnSendPhoneOtp.addEventListener("click", async () => {
    const phone = dom.inputPhoneNumber.value.trim();
    if (!phone) {
      alert("Please enter a valid phone number.");
      return;
    }
    dom.btnSendPhoneOtp.disabled = true;
    dom.btnSendPhoneOtp.textContent = "⏳ Sending OTP...";
    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      const res = await fetch("/api/v1/auth/phone/send-otp", {
        method: "POST",
        headers,
        body: JSON.stringify({ phone })
      });
      const data = await res.json();
      if (res.ok) {
        dom.phoneStep2.style.display = "block";
        if (data.dev_otp) {
          dom.otpHintText.textContent = `Verification OTP sent to ${phone}. (Auto-filled Demo Code: ${data.dev_otp})`;
          dom.inputPhoneOtp.value = data.dev_otp;
        } else {
          dom.otpHintText.textContent = `Verification OTP sent to ${phone}. Please enter the 6-digit code.`;
        }
        if (dom.phoneFeedback) {
          dom.phoneFeedback.style.color = "#10b981";
          dom.phoneFeedback.textContent = "OTP dispatched successfully!";
        }
      } else {
        alert("Failed to send OTP: " + (data.detail || "Error"));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    } finally {
      dom.btnSendPhoneOtp.disabled = false;
      dom.btnSendPhoneOtp.textContent = "📩 Send Verification OTP";
    }
  });
}

if (dom.btnVerifyPhoneOtp) {
  dom.btnVerifyPhoneOtp.addEventListener("click", async () => {
    const phone = dom.inputPhoneNumber.value.trim();
    const otp = dom.inputPhoneOtp.value.trim();
    if (!otp) {
      alert("Please enter the 6-digit OTP code.");
      return;
    }
    dom.btnVerifyPhoneOtp.disabled = true;
    dom.btnVerifyPhoneOtp.textContent = "⏳ Verifying...";
    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      const res = await fetch("/api/v1/auth/phone/verify-otp", {
        method: "POST",
        headers,
        body: JSON.stringify({ phone, otp })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`📱 Phone number ${phone} successfully verified!`);
        if (state.user) {
          state.user.phone = phone;
          state.user.phone_verified = true;
          applyUserToUI(state.user);
        }
        setTimeout(() => {
          if (dom.phoneModal) dom.phoneModal.style.display = "none";
        }, 1200);
      } else {
        alert("Verification failed: " + (data.detail || "Invalid code"));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    } finally {
      dom.btnVerifyPhoneOtp.disabled = false;
      dom.btnVerifyPhoneOtp.textContent = "✅ Verify & Link Phone";
    }
  });
}

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

// Login Form Submit
dom.formLogin.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const btn = document.getElementById("btn-submit-login");
  // Clear previous errors
  document.querySelectorAll('.auth-inline-error').forEach(el => el.remove());
  // Loading state
  btn.disabled = true;
  btn.textContent = "Signing in...";
  try {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
      localStorage.setItem("vyzn_access_token", data.access_token);
      state.token = data.access_token;
      updateUserUI(data.user);
      dom.authModal.style.display = "none";
      showToast(`Welcome back, ${data.user?.full_name || email}!`);
    } else if (res.status === 404) {
      showAuthError("No account found with this email address.", "login-email");
    } else if (res.status === 401) {
      showAuthError("Incorrect password.", "login-password");
    } else {
      showAuthError(data.detail || "Sign in failed. Please try again.", "login-password");
    }
  } catch (err) {
    showAuthError("Connection error. Please check your network and try again.", "btn-submit-login");
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign In";
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
      applyUserToUI(state.user);
      dom.authModal.style.display = "none";
      showToast(`✅ Created account for ${email} (${role.toUpperCase()})`);
      await fetchLocations();
      await fetchCameras();
      await fetchIncidents();
      await fetchClips();
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

function drawZonesOnCanvas(canvas, zones) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width || 640;
  const h = canvas.height || 360;
  ctx.clearRect(0, 0, w, h);

  if (!zones || zones.length === 0) return;

  zones.forEach(z => {
    if (!z.points || z.points.length < 3) return;
    const isRestricted = z.zone_type !== "privacy_mask";
    ctx.beginPath();
    z.points.forEach((pt, idx) => {
      const px = pt[0] * w;
      const py = pt[1] * h;
      if (idx === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.closePath();

    if (isRestricted) {
      ctx.fillStyle = "rgba(239, 68, 68, 0.2)";
      ctx.strokeStyle = "#ef4444";
      ctx.lineWidth = 2;
    } else {
      ctx.fillStyle = "rgba(15, 23, 42, 0.8)";
      ctx.strokeStyle = "#0ea5e9";
      ctx.lineWidth = 2;
    }
    ctx.fill();
    ctx.stroke();

    const first = z.points[0];
    ctx.fillStyle = isRestricted ? "#ef4444" : "#38bdf8";
    ctx.font = "bold 11px sans-serif";
    ctx.fillText((isRestricted ? "🚨 " : "🛡️ ") + z.name, first[0] * w + 4, first[1] * h + 14);
  });
}

async function fetchCameras() {
  try {
    const headers = {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    const url = state.currentLocationId ? `/api/cameras?location_id=${encodeURIComponent(state.currentLocationId)}` : "/api/cameras";
    const res = await fetch(url, { headers });
    if (!res.ok) return;
    const cams = await res.json();
    state.cameras = cams;

    // Update zone camera selector options
    if (dom.zoneCamSelect) {
      dom.zoneCamSelect.innerHTML = cams.map(c => `<option value="${c.camera_id}">${c.name}</option>`).join("");
    }

    // Update clips camera selector options
    if (dom.clipsFilterCamera) {
      dom.clipsFilterCamera.innerHTML = `<option value="all">All Cameras</option>` + cams.map(c => `<option value="${c.camera_id}">${c.name}</option>`).join("");
    }

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
    const isPhone = c.camera_id.includes("phone") || c.name.toLowerCase().includes("phone");
    const streamBadge = isWebcam ? "LIVE WEBCAM" : (isPhone ? "SMARTPHONE" : "SUB 480p");
    
    const isOnline = c.status === "online";
    const isConnecting = c.status === "connecting";
    const statusColor = isOnline ? "#10b981" : (isConnecting ? "#f59e0b" : "#ff4444");
    const statusDotClass = isOnline ? "online" : (isConnecting ? "connecting" : "offline");
    const fpsText = isOnline ? `${(c.fps_measured || c.target_fps || 4.0).toFixed(1)} FPS` : (isConnecting ? "CONNECTING..." : "OFFLINE");
    const isOfflineMode = !isOnline && !isConnecting;
    const badgeExtraClass = isOfflineMode ? "offline-high-contrast" : "";

    tile.innerHTML = `
      <div class="tile-media" style="position: relative; overflow: hidden; background: #090d16;">
        <img class="tile-stream" src="/api/cameras/${c.camera_id}/mjpeg" alt="${c.name}" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex';">
        <div class="tile-stream-fallback" style="display: ${isOfflineMode ? 'flex' : 'none'}; position: absolute; inset: 0; background: #090d16; flex-direction: column; align-items: center; justify-content: center; gap: 8px; z-index: 2;">
          <span style="font-size: 2.2rem; color: #ff4444;">📡</span>
          <strong style="color: #ffffff; font-size: 0.85rem; letter-spacing: 0.5px;">CAMERA STREAM RECONNECTING</strong>
          <span style="color: #94a3b8; font-size: 0.75rem;">Waiting for local RTSP / BYOD frame...</span>
        </div>
        <canvas class="tile-overlay-canvas" width="640" height="360"></canvas>
      </div>
      <div class="tile-hud-top">
        <div class="tile-cam-info">
          <span class="stream-dot ${statusDotClass}" style="background: ${statusColor}; box-shadow: 0 0 6px ${statusColor};"></span>
          <span class="tile-cam-name">${c.name}</span>
          <span class="stream-profile-badge ${badgeExtraClass}" id="badge-stream-${c.camera_id}" style="color:${statusColor}">${isOnline ? streamBadge : (isConnecting ? 'CONNECTING' : 'OFFLINE')}</span>
        </div>
        <div class="tile-stats">
          <span class="fps-pill ${badgeExtraClass}" style="color: ${statusColor}">${fpsText}</span>
          <span class="protocol-pill">${isWebcam ? 'DIRECT-SHOW' : (isPhone ? 'HTTP-MJPEG' : 'RTSP/TCP')}</span>
        </div>
      </div>
      <div class="tile-hud-bottom">
        <button class="hud-btn btn-stream-toggle" data-cam="${c.camera_id}" title="Toggle Main/Sub Stream">HD/SD</button>
        <button class="hud-btn btn-tile-snapshot" data-cam="${c.camera_id}" title="Capture Still Snapshot">📷 Snapshot</button>
        <button class="hud-btn btn-tile-zone" data-cam="${c.camera_id}" title="Draw Threat Zone">✏️ Zone</button>
        <button class="hud-btn btn-tile-expand" data-cam="${c.camera_id}" title="Maximize View">⛶</button>
        <button class="hud-btn btn-tile-delete" data-cam="${c.camera_id}" title="Delete Camera" style="color: #ef4444;">🗑️</button>
      </div>
    `;

    // Fetch and draw geofence zones onto tile canvas overlay
    fetch(`/api/cameras/${c.camera_id}/zones`)
      .then(r => r.ok ? r.json() : [])
      .then(zones => {
        const cvs = tile.querySelector(".tile-overlay-canvas");
        drawZonesOnCanvas(cvs, zones);
      })
      .catch(() => {});

    // Hook HUD buttons
    tile.querySelector(".btn-stream-toggle").addEventListener("click", (e) => {
      e.stopPropagation();
      const badge = tile.querySelector(".stream-profile-badge");
      if (badge) {
        const isMain = badge.textContent.includes("MAIN");
        badge.textContent = isMain ? streamBadge : "MAIN 1080p";
        badge.style.color = isMain ? statusColor : "#10b981";
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

    tile.querySelector(".btn-tile-delete").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Are you sure you want to remove camera [${c.name}] (${c.camera_id})?`)) return;
      try {
        const headers = {};
        if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
        const delRes = await fetch(`/api/cameras/${c.camera_id}`, {
          method: "DELETE",
          headers: headers
        });
        if (delRes.ok) {
          showToast(`🗑️ Camera [${c.name}] removed.`);
          await fetchCameras();
        } else {
          const err = await delRes.json();
          alert("Delete error: " + (err.detail || "Failed to remove camera"));
        }
      } catch (err) {
        alert("Network error: " + err.message);
      }
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
      <div class="standby-title">Connect New Camera</div>
      <div class="standby-sub">Connect Smartphone Camera, Laptop Webcam, or IP Camera</div>
      <button class="btn-tool" id="btn-bay-add-camera">➕ Connect Camera</button>
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
    if (state.currentLocationId) {
      params.set("location_id", state.currentLocationId);
    }
    if (dom.filterObjType && dom.filterObjType.value !== "all") {
      params.set("object_type", dom.filterObjType.value);
    }
    if (dom.filterColor && dom.filterColor.value !== "all") {
      params.set("color", dom.filterColor.value);
    }
    if (dom.filterZone && dom.filterZone.value !== "all") {
      params.set("zone", dom.filterZone.value);
    }

    const headers = {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    const res = await fetch(`/api/events?${params.toString()}`, { headers });
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
    filtered = filtered.filter(e => e.score >= 66);
  } else if (state.currentFilter === "unreviewed") {
    filtered = filtered.filter(e => e.user_triage === "unreviewed" || !e.user_triage);
  } else if (state.currentFilter === "starred") {
    filtered = filtered.filter(e => e.starred);
  }

  if (filtered.length === 0) {
    dom.incidentFeed.innerHTML = `
      <div class="empty-feed-placeholder">
        <span>🛡️ Zero matching intrusions.</span>
        <span style="font-size:0.7rem; color:var(--text-muted);">Real-time edge event stream active.</span>
      </div>
    `;
    return;
  }

  dom.incidentFeed.innerHTML = "";
  filtered.forEach(ev => {
    const card = document.createElement("div");
    const score = ev.score || 0;
    const isCritical = score >= 85;
    const isSuspicious = score >= 66 && score < 85;
    const isElevated = score >= 36 && score < 66;

    let scoreClass = "score-norm";
    let tierLabel = "NORMAL";
    if (isCritical) {
      scoreClass = "score-high";
      tierLabel = "CRITICAL";
      card.className = "incident-card threat-card";
    } else if (isSuspicious) {
      scoreClass = "score-warn";
      tierLabel = "SUSPICIOUS";
      card.className = "incident-card";
    } else if (isElevated) {
      scoreClass = "score-elevated";
      tierLabel = "ELEVATED";
      card.className = "incident-card";
    } else {
      card.className = "incident-card";
    }

    const timeFormatted = ev.start_time ? new Date(ev.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : "--:--:--";

    card.innerHTML = `
      <div class="incident-card-top">
        <img class="incident-thumb" src="/api/events/${ev.event_group_id}/thumb" alt="Thumb" onerror="this.style.display='none'">
        <div class="incident-meta">
          <div class="incident-row-1">
            <span class="incident-cam">${ev.camera_id}</span>
            <span class="incident-score-badge ${scoreClass}">${score}/100 [${tierLabel}]</span>
          </div>
          <div class="incident-row-2">
            ${(ev.object_type || 'MOTION').toUpperCase()} • ${Math.round((ev.confidence || 0.85) * 100)}%
          </div>
          <div class="incident-time">${timeFormatted}</div>
          <div class="card-attr-row">
            ${ev.dominant_color && ev.dominant_color !== 'unspecified' ? `<span class="card-attr-pill attr-${ev.dominant_color}">● ${ev.dominant_color.toUpperCase()}</span>` : ''}
            ${ev.zone_name && ev.zone_name !== 'general' ? `<span class="card-attr-pill">📍 ${ev.zone_name}</span>` : ''}
            ${ev.duration_sec ? `<span class="card-attr-pill">⏱️ ${Math.round(ev.duration_sec)}s</span>` : ''}
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
    teleBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await dispatchTelegramAlert(ev.event_group_id);
    });

    dom.incidentFeed.appendChild(card);
  });
}

async function dispatchTelegramAlert(eventId) {
  showToast(`✈️ Dispatching incident ${eventId} to Telegram...`);
  try {
    const res = await fetch(`/api/v1/events/${eventId}/dispatch-telegram`, {
      method: "POST"
    });
    const data = await res.json();
    if (res.ok && data.status === "dispatched") {
      showToast(`✅ Alert dispatched to Telegram (${data.chat_id})!`);
    } else {
      showToast(`⚠️ Telegram dispatch: ${data.detail || data.status || 'Failed'}`, false);
    }
  } catch (err) {
    showToast(`❌ Telegram dispatch error: ${err.message}`, false);
  }
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
  switchCamTab("phone");
  probeLocalDevices();
}

dom.btnQuickDiscover.addEventListener("click", openCameraSetupModal);
dom.btnCloseDiscoveryModal.addEventListener("click", () => {
  dom.discoveryModal.style.display = "none";
});

// Tabs inside Camera Setup Modal
const tabCamPhone = document.getElementById("tab-cam-phone");
const tabCamWebcam = document.getElementById("tab-cam-webcam");
const tabCamRtsp = document.getElementById("tab-cam-rtsp");
const tabCamOnvif = document.getElementById("tab-cam-onvif");
const paneCamPhone = document.getElementById("pane-cam-phone");
const paneCamWebcam = document.getElementById("pane-cam-webcam");
const paneCamRtsp = document.getElementById("pane-cam-rtsp");
const paneCamOnvif = document.getElementById("pane-cam-onvif");

function switchCamTab(tabName) {
  if (tabCamPhone) tabCamPhone.classList.toggle("active", tabName === "phone");
  if (tabCamWebcam) tabCamWebcam.classList.toggle("active", tabName === "webcam");
  if (tabCamRtsp) tabCamRtsp.classList.toggle("active", tabName === "rtsp");
  if (tabCamOnvif) tabCamOnvif.classList.toggle("active", tabName === "onvif");

  if (paneCamPhone) paneCamPhone.style.display = tabName === "phone" ? "flex" : "none";
  if (paneCamWebcam) paneCamWebcam.style.display = tabName === "webcam" ? "flex" : "none";
  if (paneCamRtsp) paneCamRtsp.style.display = tabName === "rtsp" ? "flex" : "none";
  if (paneCamOnvif) paneCamOnvif.style.display = tabName === "onvif" ? "flex" : "none";
}

if (tabCamPhone) tabCamPhone.addEventListener("click", () => switchCamTab("phone"));
if (tabCamWebcam) tabCamWebcam.addEventListener("click", () => switchCamTab("webcam"));
if (tabCamRtsp) tabCamRtsp.addEventListener("click", () => switchCamTab("rtsp"));
if (tabCamOnvif) tabCamOnvif.addEventListener("click", () => switchCamTab("onvif"));

// 1-Click Adopt Smartphone Camera (IP Webcam / DroidCam)
const btnAdoptPhoneCamera = document.getElementById("btn-adopt-phone-camera");
if (btnAdoptPhoneCamera) {
  btnAdoptPhoneCamera.addEventListener("click", async () => {
    let phoneUrl = document.getElementById("input-phone-url").value.trim();
    const camName = document.getElementById("input-phone-name").value.trim() || "Smartphone Camera";
    const camId = `cam_phone_${Date.now()}`;

    if (!phoneUrl) {
      alert("Please enter your phone camera stream URL (e.g. http://192.168.1.15:8080/video)");
      return;
    }

    // Auto-correct common IP Webcam omissions: if port 8080 or 4747 is specified without path, append /video
    if (phoneUrl.includes(":8080") && !phoneUrl.includes("/video") && !phoneUrl.includes("/shot")) {
      phoneUrl = phoneUrl.replace(/\/+$/, "") + "/video";
    } else if (phoneUrl.includes(":4747") && !phoneUrl.includes("/video")) {
      phoneUrl = phoneUrl.replace(/\/+$/, "") + "/video";
    }

    btnAdoptPhoneCamera.disabled = true;
    btnAdoptPhoneCamera.textContent = "⏳ Probing Stream Connection...";

    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      const res = await fetch("/api/v1/cameras/adopt", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          camera_id: camId,
          name: camName,
          rtsp_url: phoneUrl,
          target_fps: 4.0,
          location_id: state.currentLocationId,
          probe_connection: true
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.warning) {
          showToast(`⚠️ [${camName}] added (Device is currently OFFLINE)`);
        } else {
          showToast(`📱 Smartphone Camera [${camName}] connected live!`);
        }
        dom.discoveryModal.style.display = "none";
        await fetchCameras();
      } else {
        const err = await res.json();
        alert("Camera Connection Error:\n\n" + (err.detail || "Cannot establish video connection to smartphone. Ensure phone Wi-Fi is on and IP Webcam server is running."));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    } finally {
      btnAdoptPhoneCamera.disabled = false;
      btnAdoptPhoneCamera.textContent = "📱 Connect Smartphone Camera";
    }
  });
}

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
      } else {
        select.innerHTML = `<option value="0">Default USB Webcam (Device 0)</option>`;
      }
    }
  } catch (err) {
    console.error("Local device probe failed:", err);
  }
}

// 1-Click Adopt Local Webcam
const btnAdoptPhysicalWebcam = document.getElementById("btn-adopt-physical-webcam");
if (btnAdoptPhysicalWebcam) {
  btnAdoptPhysicalWebcam.addEventListener("click", async () => {
    const devIdx = document.getElementById("select-local-device").value;
    const camName = document.getElementById("input-webcam-name").value.trim() || `Physical Webcam ${devIdx}`;
    const camId = `cam_webcam_${devIdx}`;

    btnAdoptPhysicalWebcam.disabled = true;
    btnAdoptPhysicalWebcam.textContent = "⏳ Probing Local Video Device...";

    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      const res = await fetch("/api/v1/cameras/adopt", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          camera_id: camId,
          name: camName,
          rtsp_url: devIdx,
          target_fps: 4.0,
          location_id: state.currentLocationId,
          probe_connection: true
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.warning) {
          showToast(`⚠️ [${camName}] added (Device is currently OFFLINE)`);
        } else {
          showToast(`✅ Physical camera [${camName}] connected live!`);
        }
        dom.discoveryModal.style.display = "none";
        await fetchCameras();
      } else {
        const err = await res.json();
        alert("Camera Connection Error:\n\n" + (err.detail || "Unable to open physical video capture device."));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    } finally {
      btnAdoptPhysicalWebcam.disabled = false;
      btnAdoptPhysicalWebcam.textContent = "⚡ Connect Physical Camera to Cockpit";
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

    btnAdoptManualRtsp.disabled = true;
    btnAdoptManualRtsp.textContent = "⏳ Probing RTSP Stream...";

    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      const res = await fetch("/api/v1/cameras/adopt", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          camera_id: camId,
          name: camName,
          rtsp_url: rtspUrl,
          target_fps: fps,
          location_id: state.currentLocationId,
          probe_connection: true
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.warning) {
          showToast(`⚠️ [${camName}] added to matrix (Currently OFFLINE)`);
        } else {
          showToast(`✅ Network camera [${camName}] added to matrix!`);
        }
        dom.discoveryModal.style.display = "none";
        await fetchCameras();
      } else {
        const err = await res.json();
        alert("RTSP Connection Error:\n\n" + (err.detail || "Connection timed out or failed. Verify camera RTSP URL and credentials."));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    } finally {
      btnAdoptManualRtsp.disabled = false;
      btnAdoptManualRtsp.textContent = "🌐 Connect Network RTSP Camera";
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
          <span style="color:#38bdf8; cursor:pointer;" onclick="document.getElementById('tab-cam-phone').click()">👉 Switch to "Smartphone Camera" tab to connect your phone!</span>
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
          const headers = { "Content-Type": "application/json" };
          if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
          const adoptRes = await fetch("/api/v1/cameras/adopt", {
            method: "POST",
            headers: headers,
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

dom.btnReplayTelegram.addEventListener("click", async () => {
  if (state.activeReplayEvent) {
    await dispatchTelegramAlert(state.activeReplayEvent.event_group_id);
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
function switchStage(stageName) {
  if (dom.cockpitStage) dom.cockpitStage.style.display = stageName === "cockpit" ? "block" : "none";
  if (dom.floorplanStage) dom.floorplanStage.style.display = stageName === "map" ? "flex" : "none";
  if (dom.clipsStage) dom.clipsStage.style.display = stageName === "clips" ? "flex" : "none";
  if (dom.searchStage) dom.searchStage.style.display = stageName === "search" ? "flex" : "none";

  if (dom.navCockpit) dom.navCockpit.classList.toggle("active", stageName === "cockpit");
  if (dom.navClips) dom.navClips.classList.toggle("active", stageName === "clips");
  if (dom.navSearch) dom.navSearch.classList.toggle("active", stageName === "search");
  if (dom.navMap) dom.navMap.classList.toggle("active", stageName === "map");

  if (stageName === "clips") {
    fetchClips();
  } else if (stageName === "search") {
    populateSearchCameraSelect();
    executeForensicSearch();
  }
}

if (dom.navCockpit) {
  dom.navCockpit.addEventListener("click", () => switchStage("cockpit"));
}

if (dom.navClips) {
  dom.navClips.addEventListener("click", () => switchStage("clips"));
}

if (dom.navSearch) {
  dom.navSearch.addEventListener("click", () => switchStage("search"));
}

if (dom.navMap) {
  dom.navMap.addEventListener("click", (e) => {
    e.preventDefault();
    showToast("❌ Layout Radar is disabled at this stage", false);
  });
}

// Map camera click to focus in cockpit
document.querySelectorAll(".map-cam-group").forEach(grp => {
  grp.addEventListener("click", () => {
    const camId = grp.getAttribute("data-cam");
    showToast(`📹 Focusing Cockpit on [${camId}]...`);
    switchStage("cockpit");
    const tile = document.getElementById(`tile-${camId}`);
    if (tile) {
      tile.scrollIntoView({ behavior: "smooth", block: "center" });
      tile.style.outline = "2px solid #10b981";
      setTimeout(() => tile.style.outline = "none", 2000);
    }
  });
});

if (dom.navZones) {
  dom.navZones.addEventListener("click", () => {
    openZoneStudio(state.activeCamera);
  });
}

if (dom.navDiscovery) {
  dom.navDiscovery.addEventListener("click", openCameraSetupModal);
}

if (dom.navDpdp) {
  dom.navDpdp.addEventListener("click", () => {
    window.open("/api/dpdp/notice", "_blank");
  });
}

// ===========================================================================
// Dedicated Clips & Incident Footage Gallery
// ===========================================================================
async function fetchClips() {
  if (!dom.clipsGrid) return;
  dom.clipsGrid.innerHTML = `
    <div class="empty-clips-placeholder">
      <span class="spinner"></span>
      <span>Loading verified footage recordings...</span>
    </div>
  `;
  try {
    const headers = {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    let url = `/api/events?limit=100`;
    if (state.currentLocationId) {
      url += `&location_id=${encodeURIComponent(state.currentLocationId)}`;
    }
    const res = await fetch(url, { headers });
    if (!res.ok) return;
    const events = await res.json();
    state.clipsEvents = events;
    renderClipsGallery();
  } catch (err) {
    console.debug("Fetch clips error:", err);
  }
}

function renderClipsGallery() {
  if (!dom.clipsGrid) return;
  let list = state.clipsEvents || [];

  // Tier filter
  const tierFilter = dom.clipsFilterTier ? dom.clipsFilterTier.value : "all";
  if (tierFilter === "tier4") {
    list = list.filter(e => e.score >= 85);
  } else if (tierFilter === "tier3") {
    list = list.filter(e => e.score >= 66 && e.score < 85);
  } else if (tierFilter === "tier2") {
    list = list.filter(e => e.score >= 36 && e.score < 66);
  } else if (tierFilter === "tier1") {
    list = list.filter(e => e.score < 36);
  }

  // Camera filter
  const camFilter = dom.clipsFilterCamera ? dom.clipsFilterCamera.value : "all";
  if (camFilter !== "all") {
    list = list.filter(e => e.camera_id === camFilter);
  }

  if (list.length === 0) {
    dom.clipsGrid.innerHTML = `
      <div class="empty-clips-placeholder">
        <div class="empty-clips-icon">🎞️</div>
        <div><strong>No clips found for this filter.</strong></div>
        <div style="font-size: 0.8rem; color: var(--text-muted);">Clips are recorded strictly when actual motion occurs on connected cameras.</div>
      </div>
    `;
    return;
  }

  dom.clipsGrid.innerHTML = "";
  list.forEach(ev => {
    const card = document.createElement("div");
    card.className = "clip-card";

    const score = ev.score || 0;
    let tierName = "Normal";
    let tierClass = "tier-normal";
    let scoreColor = "#94a3b8";

    if (score >= 85) {
      tierName = "Tier 4: Critical";
      tierClass = "tier-critical";
      scoreColor = "#ef4444";
    } else if (score >= 66) {
      tierName = "Tier 3: Suspicious";
      tierClass = "tier-suspicious";
      scoreColor = "#f59e0b";
    } else if (score >= 36) {
      tierName = "Tier 2: Elevated";
      tierClass = "tier-elevated";
      scoreColor = "#38bdf8";
    }

    const durationSec = Math.round(ev.duration_sec || 10);
    const timeFormatted = ev.start_time ? new Date(ev.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : "--:--:--";
    const dateFormatted = ev.start_time ? new Date(ev.start_time).toLocaleDateString([], { month: 'short', day: 'numeric' }) : "";

    card.innerHTML = `
      <div class="clip-thumb-wrap">
        <img class="clip-thumb-img" src="/api/events/${ev.event_group_id}/thumb" alt="Incident Clip" onerror="this.src='/static/thumb_placeholder.jpg'">
        <span class="clip-duration-pill">⏱️ ${durationSec}s</span>
        <span class="clip-tier-badge ${tierClass}">${tierName}</span>
      </div>
      <div class="clip-card-body">
        <div class="clip-title-row">
          <span class="clip-cam-name" title="${ev.camera_id}">📹 ${ev.camera_id}</span>
          <span class="clip-score-pill" style="color: ${scoreColor}; background: rgba(255,255,255,0.06);">${score}/100</span>
        </div>
        <div class="clip-meta-row">
          <span class="clip-time">📅 ${dateFormatted} ${timeFormatted}</span>
          <span>${(ev.object_type || 'PERSON').toUpperCase()}</span>
        </div>
        <div class="clip-chips-row">
          ${ev.motion_points_count ? `<span class="clip-chip">📍 ${ev.motion_points_count} motion pts</span>` : ''}
          ${ev.zone_name && ev.zone_name !== 'general' ? `<span class="clip-chip">🚨 ${ev.zone_name}</span>` : ''}
          <span class="clip-chip">🎯 ${Math.round((ev.confidence || 0.85) * 100)}% conf</span>
        </div>
      </div>
    `;

    card.addEventListener("click", () => {
      openReplayModal(ev);
    });

    dom.clipsGrid.appendChild(card);
  });
}

if (dom.clipsFilterTier) dom.clipsFilterTier.addEventListener("change", renderClipsGallery);
if (dom.clipsFilterCamera) dom.clipsFilterCamera.addEventListener("change", renderClipsGallery);
if (dom.btnRefreshClips) dom.btnRefreshClips.addEventListener("click", fetchClips);

// ===========================================================================
// 10b. Forensic Search & Evidence Investigation (Flow 7)
// ===========================================================================
function populateSearchCameraSelect() {
  if (!dom.searchSelectCam) return;
  const currentVal = dom.searchSelectCam.value;
  dom.searchSelectCam.innerHTML = '<option value="all">All Cameras</option>';
  (state.cameras || []).forEach(c => {
    const opt = document.createElement("option");
    opt.value = c.camera_id;
    opt.textContent = `${c.name || c.camera_id} (${c.camera_id})`;
    dom.searchSelectCam.appendChild(opt);
  });
  if (currentVal) dom.searchSelectCam.value = currentVal;
}

async function executeForensicSearch() {
  if (!dom.searchResultsGrid) return;
  dom.searchResultsGrid.innerHTML = `
    <div class="empty-clips-placeholder">
      <span class="spinner"></span>
      <span>Querying multi-dimensional forensic evidence index...</span>
    </div>
  `;

  try {
    const params = new URLSearchParams();
    params.set("limit", "100");
    if (state.currentLocationId) params.set("location_id", state.currentLocationId);

    const q = dom.searchInputQuery ? dom.searchInputQuery.value.trim() : "";
    if (q) params.set("q", q);

    const objType = dom.searchSelectObj ? dom.searchSelectObj.value : "all";
    if (objType && objType !== "all") params.set("object_type", objType);

    const color = dom.searchSelectColor ? dom.searchSelectColor.value : "all";
    if (color && color !== "all") params.set("color", color);

    const zone = dom.searchSelectZone ? dom.searchSelectZone.value : "all";
    if (zone && zone !== "all") params.set("zone", zone);

    const cam = dom.searchSelectCam ? dom.searchSelectCam.value : "all";
    if (cam && cam !== "all") params.set("camera_id", cam);

    const minScore = dom.searchSliderScore ? parseInt(dom.searchSliderScore.value, 10) : 0;
    if (minScore > 0) params.set("min_score", minScore.toString());

    const dateFrom = dom.searchDateFrom && dom.searchDateFrom.value ? new Date(dom.searchDateFrom.value).toISOString() : "";
    if (dateFrom) params.set("date_from", dateFrom);

    const dateTo = dom.searchDateTo && dom.searchDateTo.value ? new Date(dom.searchDateTo.value).toISOString() : "";
    if (dateTo) params.set("date_to", dateTo);

    const headers = {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;

    const res = await fetch(`/api/v1/forensics/search?${params.toString()}`, { headers });
    if (!res.ok) {
      dom.searchResultsGrid.innerHTML = `
        <div class="empty-clips-placeholder">
          <div class="empty-clips-icon">⚠️</div>
          <span>Search query returned HTTP ${res.status}.</span>
        </div>
      `;
      return;
    }

    const data = await res.json();
    const results = data.results || [];

    if (dom.searchResultsCount) {
      dom.searchResultsCount.textContent = `${data.count || results.length} matching incident${results.length === 1 ? '' : 's'}`;
    }

    if (results.length === 0) {
      dom.searchResultsGrid.innerHTML = `
        <div class="empty-clips-placeholder">
          <div class="empty-clips-icon">🔍</div>
          <span>Zero matching forensic incidents found for current criteria.</span>
          <span style="font-size: 0.75rem; color: var(--text-muted);">Try loosening search filters or resetting date constraints.</span>
        </div>
      `;
      return;
    }

    dom.searchResultsGrid.innerHTML = "";
    results.forEach(ev => {
      const card = document.createElement("div");
      card.className = "clip-card";

      const score = ev.score || 0;
      let tierName = "Tier 1: Normal";
      let tierClass = "tier-normal";
      let scoreColor = "#94a3b8";

      if (score >= 85) {
        tierName = "Tier 4: Critical";
        tierClass = "tier-critical";
        scoreColor = "#ef4444";
      } else if (score >= 66) {
        tierName = "Tier 3: Suspicious";
        tierClass = "tier-suspicious";
        scoreColor = "#f59e0b";
      } else if (score >= 36) {
        tierName = "Tier 2: Elevated";
        tierClass = "tier-elevated";
        scoreColor = "#38bdf8";
      }

      const durationSec = Math.round(ev.duration_sec || 10);
      const timeFormatted = ev.start_time ? new Date(ev.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : "--:--:--";
      const dateFormatted = ev.start_time ? new Date(ev.start_time).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : "";

      card.innerHTML = `
        <div class="clip-thumb-wrap">
          <img class="clip-thumb-img" src="/api/events/${ev.event_group_id}/thumb" alt="Incident Clip" onerror="this.src='/static/thumb_placeholder.jpg'">
          <span class="clip-duration-pill">⏱️ ${durationSec}s</span>
          <span class="clip-tier-badge ${tierClass}">${tierName}</span>
        </div>
        <div class="clip-card-body">
          <div class="clip-title-row">
            <span class="clip-cam-name" title="${ev.camera_id}">📹 ${ev.camera_id}</span>
            <span class="clip-score-pill" style="color: ${scoreColor}; background: rgba(255,255,255,0.06);">${score}/100</span>
          </div>
          <div class="clip-meta-row">
            <span class="clip-time">📅 ${dateFormatted} ${timeFormatted}</span>
            <span>${(ev.object_type || 'PERSON').toUpperCase()}</span>
          </div>
          <div class="clip-chips-row">
            ${ev.dominant_color && ev.dominant_color !== 'unspecified' ? `<span class="clip-chip" style="color: #38bdf8;">● ${ev.dominant_color.toUpperCase()}</span>` : ''}
            ${ev.zone_name && ev.zone_name !== 'general' ? `<span class="clip-chip" style="color: #f59e0b;">📍 ${ev.zone_name}</span>` : ''}
            <span class="clip-chip">🎯 ${Math.round((ev.confidence || 0.85) * 100)}% conf</span>
          </div>
          <div style="display: flex; gap: 6px; margin-top: 8px;">
            <button type="button" class="btn-card-action btn-forensic-pack" style="flex: 1; padding: 4px; font-size: 0.7rem; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8; border-radius: 4px; cursor: pointer;">
              📦 Evidence Pack
            </button>
            <button type="button" class="btn-card-action btn-dispatch-tele" style="flex: 1; padding: 4px; font-size: 0.7rem; background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.3); color: #7dd3fc; border-radius: 4px; cursor: pointer;">
              ✈️ Telegram
            </button>
          </div>
        </div>
      `;

      card.addEventListener("click", (e) => {
        if (e.target.closest(".btn-card-action")) return;
        openReplayModal(ev);
      });

      const packBtn = card.querySelector(".btn-forensic-pack");
      if (packBtn) {
        packBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          window.location.href = `/api/v1/events/${ev.event_group_id}/forensic-pack`;
          showToast(`📦 Exporting BSA 2023 Forensic Evidence Pack for [${ev.event_group_id}]...`);
        });
      }

      const teleBtn = card.querySelector(".btn-dispatch-tele");
      if (teleBtn) {
        teleBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          await dispatchTelegramAlert(ev.event_group_id);
        });
      }

      dom.searchResultsGrid.appendChild(card);
    });

  } catch (err) {
    console.error("Forensic search error:", err);
    if (dom.searchResultsGrid) {
      dom.searchResultsGrid.innerHTML = `
        <div class="empty-clips-placeholder">
          <div class="empty-clips-icon">❌</div>
          <span>Failed to query forensic database: ${err.message}</span>
        </div>
      `;
    }
  }
}

function resetSearchFilters() {
  if (dom.searchInputQuery) dom.searchInputQuery.value = "";
  if (dom.searchSelectObj) dom.searchSelectObj.value = "all";
  if (dom.searchSelectColor) dom.searchSelectColor.value = "all";
  if (dom.searchSelectZone) dom.searchSelectZone.value = "all";
  if (dom.searchSelectCam) dom.searchSelectCam.value = "all";
  if (dom.searchDateFrom) dom.searchDateFrom.value = "";
  if (dom.searchDateTo) dom.searchDateTo.value = "";
  if (dom.searchSliderScore) {
    dom.searchSliderScore.value = "0";
    if (dom.searchScoreVal) dom.searchScoreVal.textContent = "0 / 100";
  }
  executeForensicSearch();
}

if (dom.btnRunSearch) dom.btnRunSearch.addEventListener("click", executeForensicSearch);
if (dom.btnResetSearch) dom.btnResetSearch.addEventListener("click", resetSearchFilters);
if (dom.searchInputQuery) {
  dom.searchInputQuery.addEventListener("keydown", (e) => {
    if (e.key === "Enter") executeForensicSearch();
  });
}
if (dom.searchSliderScore) {
  dom.searchSliderScore.addEventListener("input", () => {
    if (dom.searchScoreVal) dom.searchScoreVal.textContent = `${dom.searchSliderScore.value} / 100`;
  });
  dom.searchSliderScore.addEventListener("change", executeForensicSearch);
}
if (dom.searchSelectObj) dom.searchSelectObj.addEventListener("change", executeForensicSearch);
if (dom.searchSelectColor) dom.searchSelectColor.addEventListener("change", executeForensicSearch);
if (dom.searchSelectZone) dom.searchSelectZone.addEventListener("change", executeForensicSearch);
if (dom.searchSelectCam) dom.searchSelectCam.addEventListener("change", executeForensicSearch);


// ===========================================================================
// Property Location Management
// ===========================================================================
async function fetchLocations() {
  try {
    const headers = {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    const res = await fetch("/api/v1/locations", { headers });
    if (!res.ok) return;
    const locs = await res.json();
    state.locations = locs;

    if (!state.locations.find(l => l.location_id === state.currentLocationId)) {
      if (state.locations.length > 0) {
        state.currentLocationId = state.locations[0].location_id;
      }
    }

    const curLoc = state.locations.find(l => l.location_id === state.currentLocationId);
    if (curLoc && dom.siteNameDisplay) {
      dom.siteNameDisplay.textContent = curLoc.name;
    }

    if (dom.siteOptionsList) {
      dom.siteOptionsList.innerHTML = state.locations.map(loc => `
        <div class="site-option ${loc.location_id === state.currentLocationId ? 'active' : ''}" data-id="${loc.location_id}" data-name="${loc.name}">
          <span class="site-opt-dot"></span>
          <div class="site-opt-info">
            <span class="site-opt-name">${loc.name}</span>
            <span class="site-opt-meta">${loc.address || 'Property Location'}</span>
          </div>
          ${loc.location_id === state.currentLocationId ? '<span class="site-opt-check">✓</span>' : ''}
        </div>
      `).join("");

      dom.siteOptionsList.querySelectorAll(".site-option").forEach(opt => {
        opt.addEventListener("click", () => {
          const locId = opt.getAttribute("data-id");
          const locName = opt.getAttribute("data-name");
          state.currentLocationId = locId;
          dom.siteNameDisplay.textContent = locName;
          dom.siteDropdownMenu.style.display = "none";
          showToast(`📍 Switched location to [${locName}]`);
          fetchCameras();
          fetchIncidents();
          fetchClips();
          fetchLocations();
        });
      });
    }
  } catch (err) {
    console.debug("Fetch locations error:", err);
  }
}

if (dom.btnSiteToggle) {
  dom.btnSiteToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const isHidden = dom.siteDropdownMenu.style.display === "none";
    dom.siteDropdownMenu.style.display = isHidden ? "block" : "none";
  });

  document.addEventListener("click", (e) => {
    if (dom.siteDropdownMenu && !dom.siteDropdownMenu.contains(e.target) && e.target !== dom.btnSiteToggle) {
      dom.siteDropdownMenu.style.display = "none";
    }
  });
}

if (dom.btnOpenAddLocationModal) {
  dom.btnOpenAddLocationModal.addEventListener("click", () => {
    dom.siteDropdownMenu.style.display = "none";
    if (dom.locationModal) dom.locationModal.style.display = "flex";
  });
}

if (dom.btnCloseLocationModal) {
  dom.btnCloseLocationModal.addEventListener("click", () => {
    if (dom.locationModal) dom.locationModal.style.display = "none";
  });
}

if (dom.formAddLocation) {
  dom.formAddLocation.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = dom.locNameInput.value.trim();
    const address = dom.locAddrInput.value.trim();
    if (!name) return;

    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      const res = await fetch("/api/v1/locations", {
        method: "POST",
        headers,
        body: JSON.stringify({ name, address })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`📍 Added property location: ${data.name}`);
        state.currentLocationId = data.location_id;
        dom.locationModal.style.display = "none";
        dom.locNameInput.value = "";
        dom.locAddrInput.value = "";
        await fetchLocations();
        await fetchCameras();
        await fetchIncidents();
        await fetchClips();
      } else {
        alert("Failed to add location: " + (data.detail || "Error"));
      }
    } catch (err) {
      alert("Network error: " + err.message);
    }
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
// 11. Telegram Alert Center & Two-Way Triage Controls
// ===========================================================================
async function fetchTelegramStatus() {
  try {
    const res = await fetch("/api/v1/alerts/telegram");
    if (!res.ok) return;
    const data = await res.json();

    // Update Top Navigation Bar Status Pill
    if (dom.headerTeleDot) {
      if (data.configured && data.poller_active) {
        dom.headerTeleDot.className = "tele-status-dot active";
        if (dom.headerTeleLabel) dom.headerTeleLabel.textContent = "✈️ Bot Active";
      } else if (data.configured) {
        dom.headerTeleDot.className = "tele-status-dot";
        if (dom.headerTeleLabel) dom.headerTeleLabel.textContent = "✈️ Bot Paused";
      } else {
        dom.headerTeleDot.className = "tele-status-dot";
        if (dom.headerTeleLabel) dom.headerTeleLabel.textContent = "✈️ Bot Setup";
      }
    }

    // Update Modal Status Banner if open
    if (dom.modalTeleDot && dom.modalTeleStatusTitle && dom.modalTeleStatusDesc) {
      if (data.configured && data.poller_active) {
        dom.modalTeleDot.className = "status-indicator-dot active";
        dom.modalTeleStatusTitle.textContent = `🟢 Connected & Operational (Chat: ${data.chat_id_masked})`;
        dom.modalTeleStatusDesc.textContent = "Two-way long-polling poller active. Interactive inline keyboard triage enabled.";
      } else if (data.configured) {
        dom.modalTeleDot.className = "status-indicator-dot offline";
        dom.modalTeleStatusTitle.textContent = `🟡 Configured (Poller Standby, Chat: ${data.chat_id_masked})`;
        dom.modalTeleStatusDesc.textContent = "Bot credentials saved, but outbound long-polling worker is inactive.";
      } else {
        dom.modalTeleDot.className = "status-indicator-dot";
        dom.modalTeleStatusTitle.textContent = "⚪ Unconfigured (Simulation Fallback)";
        dom.modalTeleStatusDesc.textContent = "Enter your BotFather token and chat ID to enable live push alerts and two-way inline triage.";
      }
    }

    if (dom.inputTelegramChat && data.raw_chat_id && !dom.inputTelegramChat.value) {
      dom.inputTelegramChat.value = data.raw_chat_id;
    }
  } catch (err) {
    console.debug("Telegram status poll error:", err);
  }
}

if (dom.btnOpenTelegramModal) {
  dom.btnOpenTelegramModal.addEventListener("click", () => {
    fetchTelegramStatus();
    if (dom.testPingResult) dom.testPingResult.style.display = "none";
    if (dom.telegramModal) dom.telegramModal.style.display = "flex";
  });
}

if (dom.btnCloseTelegramModal) {
  dom.btnCloseTelegramModal.addEventListener("click", () => {
    if (dom.telegramModal) dom.telegramModal.style.display = "none";
  });
}

// Test Ping Button
if (dom.btnTelegramTestPing) {
  dom.btnTelegramTestPing.addEventListener("click", async () => {
    const token = dom.inputTelegramToken ? dom.inputTelegramToken.value.trim() : "";
    const chat = dom.inputTelegramChat ? dom.inputTelegramChat.value.trim() : "";

    dom.btnTelegramTestPing.disabled = true;
    dom.btnTelegramTestPing.textContent = "⏳ Testing Connection...";
    if (dom.testPingResult) dom.testPingResult.style.display = "none";

    try {
      const res = await fetch("/api/v1/alerts/telegram/test-ping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: token || null, chat_id: chat || null })
      });
      const data = await res.json();

      if (res.ok && data.ok) {
        if (dom.testPingResult) {
          dom.testPingResult.className = "test-ping-result success";
          dom.testPingResult.textContent = `✅ Success! Bot @${data.bot_username} verified. Deliverability round-trip: ${data.latency_ms}ms.`;
          dom.testPingResult.style.display = "block";
        }
        showToast(`✅ Verified Telegram Bot @${data.bot_username} (${data.latency_ms}ms)!`);
      } else {
        if (dom.testPingResult) {
          dom.testPingResult.className = "test-ping-result error";
          dom.testPingResult.textContent = `❌ Ping Failed: ${data.detail || data.error || 'Check token & chat ID'}`;
          dom.testPingResult.style.display = "block";
        }
        showToast("❌ Telegram test ping failed.", false);
      }
    } catch (err) {
      if (dom.testPingResult) {
        dom.testPingResult.className = "test-ping-result error";
        dom.testPingResult.textContent = `❌ Network error: ${err.message}`;
        dom.testPingResult.style.display = "block";
      }
    } finally {
      dom.btnTelegramTestPing.disabled = false;
      dom.btnTelegramTestPing.textContent = "🔔 Send Test Verification Alert";
    }
  });
}

// Save Config Button
if (dom.btnSaveTelegramConfig) {
  dom.btnSaveTelegramConfig.addEventListener("click", async () => {
    const token = dom.inputTelegramToken ? dom.inputTelegramToken.value.trim() : "";
    const chat = dom.inputTelegramChat ? dom.inputTelegramChat.value.trim() : "";
    const enablePoller = dom.checkEnablePoller ? dom.checkEnablePoller.checked : true;

    dom.btnSaveTelegramConfig.disabled = true;
    dom.btnSaveTelegramConfig.textContent = "⏳ Saving...";

    try {
      const res = await fetch("/api/v1/alerts/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_token: token || null,
          chat_id: chat || null,
          enable_poller: enablePoller
        })
      });
      const data = await res.json();
      if (res.ok && data.status === "updated") {
        showToast("💾 Saved Telegram Bot configuration!");
        await fetchTelegramStatus();
        setTimeout(() => {
          if (dom.telegramModal) dom.telegramModal.style.display = "none";
        }, 1200);
      } else {
        showToast("❌ Failed to update Telegram settings", false);
      }
    } catch (err) {
      showToast(`❌ Error: ${err.message}`, false);
    } finally {
      dom.btnSaveTelegramConfig.disabled = false;
      dom.btnSaveTelegramConfig.textContent = "💾 Save & Activate Bot";
    }
  });
}

// ===========================================================================
// 12. Initial Startup & Polling
// ===========================================================================
checkAuthSession();
fetchLocations();
fetchCameras();
fetchTelemetry();
fetchIncidents();
fetchClips();
fetchTelegramStatus();

setInterval(fetchTelemetry, 2500);
setInterval(fetchIncidents, 3500);
setInterval(fetchClips, 5000);
setInterval(fetchTelegramStatus, 15000);

// ===========================================================================
// 13. Pre-Qualification Free Trial Modal & Conversion Handlers
// ===========================================================================
function initTrialModalHandlers() {
  const modalTrial = document.getElementById("trial-modal");
  const btnOpenHeader = document.getElementById("btn-open-trial-modal");
  const btnOpenHero = document.getElementById("btn-hero-free-trial");
  const btnClose = document.getElementById("btn-close-trial-modal");
  const formTrial = document.getElementById("form-free-trial");
  const successScreen = document.getElementById("trial-success-screen");
  const btnProceed = document.getElementById("btn-trial-proceed-cockpit");
  const btnScrollCockpit = document.getElementById("btn-scroll-to-cockpit");

  function openTrial() {
    if (modalTrial) {
      modalTrial.style.display = "flex";
      if (formTrial) formTrial.style.display = "block";
      if (successScreen) successScreen.style.display = "none";
    }
  }

  function closeTrial() {
    if (modalTrial) modalTrial.style.display = "none";
  }

  if (btnOpenHeader) btnOpenHeader.addEventListener("click", openTrial);
  if (btnOpenHero) btnOpenHero.addEventListener("click", openTrial);
  if (btnClose) btnClose.addEventListener("click", closeTrial);

  if (btnScrollCockpit) {
    btnScrollCockpit.addEventListener("click", () => {
      const target = document.querySelector(".vms-shell") || document.getElementById("vms-shell");
      if (target) {
        target.scrollIntoView({ behavior: "smooth" });
      }
    });
  }

  if (btnProceed) {
    btnProceed.addEventListener("click", () => {
      closeTrial();
      const target = document.querySelector(".vms-shell") || document.getElementById("vms-shell");
      if (target) target.scrollIntoView({ behavior: "smooth" });
    });
  }

  if (formTrial) {
    formTrial.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btnSubmit = document.getElementById("btn-submit-trial");
      if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.textContent = "⏳ Provisioning Trial Instance...";
      }

      const payload = {
        full_name: document.getElementById("trial-full-name")?.value || "",
        store_name: document.getElementById("trial-store-name")?.value || "",
        city: document.getElementById("trial-city")?.value || "",
        phone: document.getElementById("trial-phone")?.value || "",
        cameras: document.getElementById("trial-cameras")?.value || "",
        concern: document.getElementById("trial-concern")?.value || ""
      };

      try {
        await fetch("/api/v1/leads/trial", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
      } catch (err) {
        console.warn("Trial lead queued locally:", err);
      } finally {
        if (formTrial) formTrial.style.display = "none";
        if (successScreen) successScreen.style.display = "block";
        if (btnSubmit) {
          btnSubmit.disabled = false;
          btnSubmit.textContent = "⚡ Launch My Free VYZN Instance";
        }
        showToast("🎉 Free trial instance activated!");
      }
    });
  }
}

// Call trial modal initializer
initTrialModalHandlers();
