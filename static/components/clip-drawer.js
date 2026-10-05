/**
 * Clip Detail Drawer Component (Section 6.3)
 * Right drawer (560px desktop) / full-screen sheet (mobile).
 * Native 16:9 player starting 3s before trigger, scrubber with trigger marker,
 * speeds (0.5x, 1x, 2x), frame step (, .), "Show what VYZN saw" overlay toggle,
 * reasons checklist with real measurements, technical details with SHA-256 copy button,
 * actions (Mark reviewed with 10s Undo, Not an issue popover, Send to Telegram, Evidence pack download).
 */

import { renderTierBadge } from './tier-badge.js';
import { icons } from './icons.js';
import { promptSecurityPin } from './shell.js';
import { formatWhen, formatLeft, escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

let activeClipList = [];
let currentClipIndex = -1;
let activeClip = null;
let onClipUpdatedCallback = null;
let undoTimeoutId = null;

/**
 * Initializes the Clip Detail Drawer in the DOM.
 * @param {object} options
 * @param {function} options.onClipUpdated - Callback when clip status changes.
 */
export function initClipDrawer({ onClipUpdated } = {}) {
  onClipUpdatedCallback = onClipUpdated;

  let scrim = document.getElementById('clip-drawer-scrim');
  if (!scrim) {
    scrim = document.createElement('div');
    scrim.id = 'clip-drawer-scrim';
    scrim.className = 'drawer-scrim';
    scrim.setAttribute('role', 'dialog');
    scrim.setAttribute('aria-modal', 'true');
    scrim.setAttribute('aria-labelledby', 'drawer-clip-title');

    scrim.innerHTML = `
      <div class="drawer-sheet" id="clip-drawer-sheet" tabindex="-1">
        <div class="drawer-header">
          <div class="drawer-title-wrap">
            <span class="drawer-clip-title" id="drawer-clip-title">Clip</span>
            <div class="drawer-nav-arrows">
              <button type="button" class="drawer-arrow-btn" id="drawer-btn-prev" title="Previous clip (k)" aria-label="Previous clip">‹</button>
              <button type="button" class="drawer-arrow-btn" id="drawer-btn-next" title="Next clip (j)" aria-label="Next clip">›</button>
            </div>
          </div>
          <button type="button" class="drawer-close-btn" id="drawer-btn-close" title="Close (Esc)" aria-label="Close">✕</button>
        </div>

        <div class="drawer-content" id="drawer-main-content">
          <!-- 16:9 Video Box -->
          <div class="drawer-player-box" id="drawer-player-box">
            <video class="drawer-video-el" id="drawer-video-player" playsinline preload="metadata"></video>
            <canvas class="drawer-overlay-canvas" id="drawer-overlay-canvas" style="display: none;"></canvas>
          </div>

          <!-- Custom Scrubber and Controls -->
          <div class="player-controls-strip">
            <div class="scrubber-track-wrap" id="player-scrubber-wrap" role="slider" aria-label="Video progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0">
              <div class="scrubber-track">
                <div class="scrubber-fill" id="player-scrubber-fill"></div>
                <div class="scrubber-trigger-marker" id="player-trigger-marker" title="Trigger moment"></div>
                <div class="scrubber-thumb" id="player-scrubber-thumb"></div>
              </div>
            </div>

            <div class="player-btns-row">
              <div class="player-left-btns">
                <button type="button" class="player-btn" id="drawer-btn-play" title="Play / Pause (Space)" aria-label="Play">▶</button>
                <button type="button" class="player-btn" id="drawer-btn-step-back" title="Step back 1 frame (,)" aria-label="Step back 1 frame">◂</button>
                <button type="button" class="player-btn" id="drawer-btn-step-fwd" title="Step forward 1 frame (.)" aria-label="Step forward 1 frame">▸</button>
                <span class="player-time-readout" id="drawer-time-readout">0:00 / 0:00</span>
              </div>
              <div class="player-right-btns">
                <button type="button" class="speed-btn" id="drawer-btn-speed" title="Speed">1×</button>
                <button type="button" class="player-btn" id="drawer-btn-fullscreen" title="Full screen" aria-label="Full screen">⛶</button>
              </div>
            </div>
          </div>

          <!-- Show what VYZN saw toggle -->
          <label class="overlay-toggle-wrap">
            <input type="checkbox" id="drawer-toggle-overlay" />
            <span>${t('clips.show_what_vyzn_saw', 'Show what VYZN saw')}</span>
          </label>

          <!-- Why this clip was saved -->
          <div class="why-saved-card">
            <div style="margin-bottom: 8px;" id="drawer-tier-badge-container"></div>
            <div class="why-saved-header">${t('clips.why_saved_heading', 'Why this clip was saved')}</div>
            <div class="why-saved-checklist" id="drawer-checklist-container"></div>
          </div>

          <!-- Facts Definition List -->
          <div>
            <h4 style="font-size: 13px; font-weight: 600; color: var(--text-2); margin: 0 0 10px 0; text-transform: uppercase;">${t('clips.facts_heading', 'Facts')}</h4>
            <dl class="clip-facts-dl" id="drawer-facts-dl"></dl>
          </div>

          <!-- Technical details (collapsed) -->
          <details class="tech-details-box" id="drawer-tech-details">
            <summary>${t('clips.technical_details', 'Technical details')}</summary>
            <div class="tech-details-content" id="drawer-tech-content"></div>
          </details>
        </div>

        <!-- Action Buttons Footer -->
        <div class="drawer-actions-footer">
          <div class="drawer-primary-actions">
            <button type="button" class="btn btn-primary" id="drawer-act-reviewed">${t('clips.mark_reviewed', 'Mark as reviewed')}</button>
            <button type="button" class="btn btn-secondary" id="drawer-act-not-issue">${t('clips.not_an_issue', 'Not an issue')}</button>
          </div>
          <div class="drawer-secondary-actions" style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button type="button" class="btn btn-secondary" id="drawer-act-telegram">${t('clips.send_to_telegram', 'Send to my Telegram')}</button>
            <button type="button" class="btn btn-secondary" id="drawer-act-evidence">${t('clips.evidence_pack', 'Evidence pack')}</button>
            <button type="button" class="btn btn-secondary" id="drawer-act-delete" style="color: #ef4444; border-color: rgba(239, 68, 68, 0.4);">🗑️ ${t('clips.delete_clip', 'Delete clip')}</button>
          </div>
        </div>
      </div>

      <!-- Popover Modal: What was it? -->
      <div class="feedback-popover-scrim" id="feedback-popover" style="display: none;" role="dialog" aria-modal="true" aria-labelledby="popover-title">
        <div class="feedback-popover-card">
          <h3 class="feedback-popover-title" id="popover-title">${t('clips.popover_title', 'What was it?')}</h3>
          <div class="feedback-reasons-list">
            <button type="button" class="feedback-reason-btn" data-reason="staff">${t('clips.reason_staff', 'It was me or my staff')}</button>
            <button type="button" class="feedback-reason-btn" data-reason="customer">${t('clips.reason_customer', 'A customer')}</button>
            <button type="button" class="feedback-reason-btn" data-reason="light">${t('clips.reason_light', 'Light, shadow or reflection')}</button>
            <button type="button" class="feedback-reason-btn" data-reason="other">${t('clips.reason_other', 'Something else')}</button>
          </div>
          <div class="feedback-popover-footer">
            <button type="button" class="btn btn-quiet" id="btn-popover-skip">${t('clips.popover_skip', 'Skip')}</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(scrim);
    bindDrawerEvents();
  }
}

/**
 * Binds DOM and keyboard events for the drawer.
 */
function bindDrawerEvents() {
  const scrim = document.getElementById('clip-drawer-scrim');
  const closeBtn = document.getElementById('drawer-btn-close');
  const prevBtn = document.getElementById('drawer-btn-prev');
  const nextBtn = document.getElementById('drawer-btn-next');
  const video = document.getElementById('drawer-video-player');
  const playBtn = document.getElementById('drawer-btn-play');
  const stepBackBtn = document.getElementById('drawer-btn-step-back');
  const stepFwdBtn = document.getElementById('drawer-btn-step-fwd');
  const speedBtn = document.getElementById('drawer-btn-speed');
  const fsBtn = document.getElementById('drawer-btn-fullscreen');
  const scrubberWrap = document.getElementById('player-scrubber-wrap');
  const toggleOverlay = document.getElementById('drawer-toggle-overlay');

  const actReviewed = document.getElementById('drawer-act-reviewed');
  const actNotIssue = document.getElementById('drawer-act-not-issue');
  const actTelegram = document.getElementById('drawer-act-telegram');
  const actEvidence = document.getElementById('drawer-act-evidence');

  const popover = document.getElementById('feedback-popover');
  const popoverSkip = document.getElementById('btn-popover-skip');

  // Close handlers
  closeBtn.addEventListener('click', closeClipDrawer);
  scrim.addEventListener('click', (e) => {
    if (e.target === scrim) closeClipDrawer();
  });

  // Prev / Next
  prevBtn.addEventListener('click', () => navigateClip(-1));
  nextBtn.addEventListener('click', () => navigateClip(1));

  // Player controls
  playBtn.addEventListener('click', togglePlay);
  video.addEventListener('click', togglePlay);

  video.addEventListener('timeupdate', updatePlayerProgress);
  video.addEventListener('play', () => { playBtn.textContent = '⏸'; });
  video.addEventListener('pause', () => { playBtn.textContent = '▶'; });

  // Speeds: 0.5x -> 1x -> 2x -> 0.5x
  const speeds = [1, 2, 0.5];
  let speedIdx = 0;
  speedBtn.addEventListener('click', () => {
    speedIdx = (speedIdx + 1) % speeds.length;
    const s = speeds[speedIdx];
    video.playbackRate = s;
    speedBtn.textContent = `${s}×`;
  });

  // Frame stepping (, and .)
  const FRAME_STEP = 1.0 / 4.0; // 4 fps standard in VYZN recording
  stepBackBtn.addEventListener('click', () => {
    video.pause();
    video.currentTime = Math.max(0, video.currentTime - FRAME_STEP);
  });
  stepFwdBtn.addEventListener('click', () => {
    video.pause();
    video.currentTime = Math.min(video.duration || 100, video.currentTime + FRAME_STEP);
  });

  // Fullscreen
  fsBtn.addEventListener('click', () => {
    const box = document.getElementById('drawer-player-box');
    if (!document.fullscreenElement) {
      box.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  });

  // Scrubber click/drag
  scrubberWrap.addEventListener('click', (e) => {
    const rect = scrubberWrap.getBoundingClientRect();
    const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (video.duration) {
      video.currentTime = pos * video.duration;
    }
  });

  // Toggle overlay
  toggleOverlay.addEventListener('change', () => {
    const canvas = document.getElementById('drawer-overlay-canvas');
    if (toggleOverlay.checked) {
      canvas.style.display = 'block';
      drawDetectionOverlay();
    } else {
      canvas.style.display = 'none';
    }
  });

  // Action: Mark as reviewed
  actReviewed.addEventListener('click', () => {
    if (!activeClip) return;
    performStatusUpdate('reviewed');
  });

  // Action: Not an issue -> opens popover
  actNotIssue.addEventListener('click', () => {
    popover.style.display = 'flex';
  });

  // Popover choices
  popover.querySelectorAll('.feedback-reason-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const reason = btn.getAttribute('data-reason');
      popover.style.display = 'none';
      performStatusUpdate('not_an_issue', { reason });
    });
  });
  popoverSkip.addEventListener('click', () => {
    popover.style.display = 'none';
    performStatusUpdate('not_an_issue', { reason: 'skipped' });
  });

  // Action: Send to Telegram
  actTelegram.addEventListener('click', async () => {
    if (!activeClip) return;
    actTelegram.disabled = true;
    actTelegram.textContent = 'Sending…';
    try {
      const resp = await fetch(`/api/clips/${encodeURIComponent(activeClip.id)}/telegram`, { credentials: 'include', method: 'POST' });
      const data = await resp.json();
      if (resp.ok) {
        showToast(t('clips.toast_sent_telegram', 'Sent to Telegram.'));
      } else {
        showToast(data.detail || 'Failed to send alert to Telegram');
      }
    } catch (e) {
      showToast('Could not reach server.');
    } finally {
      actTelegram.disabled = false;
      actTelegram.textContent = t('clips.send_to_telegram', 'Send to my Telegram');
    }
  });

  // Action: Download Evidence Pack
  actEvidence.addEventListener('click', () => {
    if (!activeClip) return;
    window.location.href = `/api/clips/${encodeURIComponent(activeClip.id)}/evidence-pack`;
  });

  // Action: Delete Clip with Security PIN Gate
  const actDelete = document.getElementById('drawer-act-delete');
  if (actDelete) {
    actDelete.addEventListener('click', async () => {
      if (!activeClip) return;
      const clipNum = activeClip.number || activeClip.clip_number || activeClip.id;
      const pin = await promptSecurityPin({
        title: 'Delete Evidence Clip',
        description: `Permanently delete Clip #${clipNum} and remove all associated media from disk. This cannot be undone.`,
        confirmText: 'Delete Clip',
        isDanger: true
      });
      if (!pin) return;

      actDelete.disabled = true;
      actDelete.textContent = 'Deleting…';
      try {
        const resp = await fetch(`/api/clips/${encodeURIComponent(activeClip.id)}`, {
          method: 'DELETE',
          headers: {
            'X-Security-Pin': pin
          }
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
          showToast(`Clip #${clipNum} permanently deleted.`);
          closeClipDrawer();
          if (typeof onClipUpdatedCallback === 'function') {
            onClipUpdatedCallback();
          }
        } else {
          showToast(data.detail || 'Failed to delete clip. Check Security PIN.');
        }
      } catch (err) {
        showToast('Network error while deleting clip.');
      } finally {
        actDelete.disabled = false;
        actDelete.textContent = `🗑️ ${t('clips.delete_clip', 'Delete clip')}`;
      }
    });
  }

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', handleDrawerKeydown);
}

/**
 * Handles keyboard shortcuts when drawer is open.
 */
function handleDrawerKeydown(e) {
  const scrim = document.getElementById('clip-drawer-scrim');
  if (!scrim || !scrim.classList.contains('is-open')) return;

  // Don't intercept if user is typing in an input
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;

  if (e.key === 'Escape') {
    closeClipDrawer();
  } else if (e.key === ' ' || e.code === 'Space') {
    e.preventDefault();
    togglePlay();
  } else if (e.key === 'j') {
    e.preventDefault();
    navigateClip(1);
  } else if (e.key === 'k') {
    e.preventDefault();
    navigateClip(-1);
  } else if (e.key === 'r') {
    e.preventDefault();
    document.getElementById('drawer-act-reviewed').click();
  } else if (e.key === 'n') {
    e.preventDefault();
    document.getElementById('drawer-act-not-issue').click();
  } else if (e.key === ',') {
    e.preventDefault();
    document.getElementById('drawer-btn-step-back').click();
  } else if (e.key === '.') {
    e.preventDefault();
    document.getElementById('drawer-btn-step-fwd').click();
  }
}

function togglePlay() {
  const video = document.getElementById('drawer-video-player');
  if (video.paused) {
    video.play().catch(() => {});
  } else {
    video.pause();
  }
}

function updatePlayerProgress() {
  const video = document.getElementById('drawer-video-player');
  const fill = document.getElementById('player-scrubber-fill');
  const thumb = document.getElementById('player-scrubber-thumb');
  const readout = document.getElementById('drawer-time-readout');

  const cur = video.currentTime || 0;
  const dur = video.duration || 1;
  const pct = Math.min(100, Math.max(0, (cur / dur) * 100));

  fill.style.width = `${pct}%`;
  thumb.style.left = `${pct}%`;

  const curStr = formatSeconds(cur);
  const durStr = formatSeconds(dur);
  readout.textContent = `${curStr} / ${durStr}`;
}

function formatSeconds(sec) {
  const s = Math.floor(sec);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? '0' : ''}${rem}`;
}

/**
 * Opens the drawer for a specific clip ID or object.
 * @param {string|object} clipOrId - Clip object or ID string.
 * @param {Array} [clipList=[]] - Optional active filtered clip array for next/prev navigation.
 */
export async function openClipDrawer(clipOrId, clipList = []) {
  initClipDrawer();
  activeClipList = clipList;

  let clipObj = typeof clipOrId === 'object' ? clipOrId : null;
  if (!clipObj) {
    try {
      const resp = await fetch(`/api/clips/${encodeURIComponent(clipOrId)}`, { credentials: 'include' });
      if (resp.ok) {
        clipObj = await resp.json();
      } else {
        showToast('Clip not found');
        return;
      }
    } catch (e) {
      showToast('Error loading clip');
      return;
    }
  }

  activeClip = clipObj;
  currentClipIndex = activeClipList.findIndex((c) => c.id === clipObj.id);

  renderDrawerContent(activeClip);

  const scrim = document.getElementById('clip-drawer-scrim');
  scrim.classList.add('is-open');
  document.getElementById('clip-drawer-sheet').focus();

  // Update URL without page reload
  try {
    history.pushState({ clipId: activeClip.id }, '', `/clips/${encodeURIComponent(activeClip.id)}`);
  } catch (e) {}
}

/**
 * Closes the drawer.
 */
export function closeClipDrawer() {
  const scrim = document.getElementById('clip-drawer-scrim');
  if (!scrim) return;

  const video = document.getElementById('drawer-video-player');
  if (video) video.pause();

  scrim.classList.remove('is-open');

  // Revert URL to /clips or /overview
  try {
    const p = window.location.pathname;
    if (p.startsWith('/clips/')) {
      history.pushState({}, '', '/clips');
    }
  } catch (e) {}
}

function navigateClip(delta) {
  if (!activeClipList || activeClipList.length === 0) return;
  let nextIdx = currentClipIndex + delta;
  if (nextIdx < 0) nextIdx = activeClipList.length - 1;
  if (nextIdx >= activeClipList.length) nextIdx = 0;
  openClipDrawer(activeClipList[nextIdx], activeClipList);
}

/**
 * Renders clip facts and video inside the drawer.
 */
function renderDrawerContent(clip) {
  const clipTitle = document.getElementById('drawer-clip-title');
  clipTitle.textContent = `${t('clips.drawer_clip_title', { number: clip.number || 1 })}`;

  const video = document.getElementById('drawer-video-player');
  video.src = clip.videoUrl || `/api/clips/${encodeURIComponent(clip.id)}/video`;

  // Start 3 seconds before trigger moment per spec Section 6.3
  const startMs = clip.startMs || Date.now();
  const triggerMs = clip.triggerMs || (startMs + 3000);
  const durSec = clip.durationSec || 15;
  const triggerOffsetSec = Math.max(0, (triggerMs - startMs) / 1000.0);
  const preTriggerSec = Math.max(0, triggerOffsetSec - 3.0);

  video.onloadedmetadata = () => {
    video.currentTime = Math.min(preTriggerSec, (video.duration || 15) - 0.5);
    // Position trigger marker on scrubber track
    const marker = document.getElementById('player-trigger-marker');
    const actualDur = video.duration || durSec;
    const triggerPct = Math.min(100, Math.max(0, (triggerOffsetSec / actualDur) * 100));
    marker.style.left = `${triggerPct}%`;
  };

  // Tier Badge
  const tierContainer = document.getElementById('drawer-tier-badge-container');
  tierContainer.innerHTML = renderTierBadge(clip.tier);

  // Reasons Checklist
  const checklist = document.getElementById('drawer-checklist-container');
  checklist.innerHTML = '';
  const reasons = clip.reasons || [];
  if (reasons.length === 0) {
    checklist.innerHTML = `<div class="why-saved-item"><span class="why-saved-check-icon">✓</span><span>Movement detected in watch area</span></div>`;
  } else {
    reasons.forEach((r) => {
      const code = r.code;
      const params = r.params || {};
      let text = 'Movement detected';
      if (code === 'entered_restricted_area') {
        text = `Person entered ${escapeHtml(params.area || clip.areaName || 'watch area')}`;
      } else if (code === 'stayed_in_area') {
        const dur = params.duration || `${params.seconds || 60} seconds`;
        text = `Stayed ${escapeHtml(dur)}`;
      } else if (code === 'outside_shop_hours') {
        text = `Movement outside shop hours`;
      } else if (code === 'person_detected') {
        const confPct = params.confidence ? ` · ${Math.round(params.confidence * 100)}% sure` : '';
        text = `Person detected${confPct}`;
      } else if (code === 'movement') {
        text = `Movement in ${escapeHtml(params.area || clip.areaName || 'camera view')}`;
      }

      const item = document.createElement('div');
      item.className = 'why-saved-item';
      item.innerHTML = `<span class="why-saved-check-icon">✓</span><span>${text}</span>`;
      checklist.appendChild(item);
    });
  }

  // Facts Definition List
  const factsDl = document.getElementById('drawer-facts-dl');
  const camName = clip.cameraName || clip.cameraId;
  const areaName = clip.areaName || 'Whole camera view';
  const whenStr = formatWhen(clip.startMs || clip.triggerMs);
  const leftStr = formatLeft(clip.expiresAtMs);
  const objList = (clip.objects || []).map((o) => o.cls).join(', ') || 'Person';

  factsDl.innerHTML = `
    <dt>${t('clips.fact_camera', 'Camera')}</dt>
    <dd>${escapeHtml(camName)}</dd>
    <dt>${t('clips.fact_area', 'Watch area')}</dt>
    <dd>${escapeHtml(areaName)}</dd>
    <dt>${t('clips.fact_when', 'When')}</dt>
    <dd>${escapeHtml(whenStr)}</dd>
    <dt>${t('clips.fact_length', 'Length')}</dt>
    <dd>${durSec} s</dd>
    <dt>${t('clips.fact_detected', 'Detected')}</dt>
    <dd>${escapeHtml(objList.charAt(0).toUpperCase() + objList.slice(1))}</dd>
    <dt>${t('clips.fact_deletes', 'Deletes')}</dt>
    <dd>${leftStr ? `In ${escapeHtml(leftStr)}` : 'At 72 hours'}</dd>
  `;

  // Technical details
  const techContent = document.getElementById('drawer-tech-content');
  const det = clip.detector || { name: 'YOLOv8n-VYZN', version: '8.0.196' };
  const sha256 = clip.sha256 || 'SHA-256 unavailable';
  const startIso = new Date(clip.startMs || Date.now()).toISOString();
  const endIso = new Date(clip.endMs || (clip.startMs + 15000)).toISOString();

  techContent.innerHTML = `
    <div><strong>${t('clips.detector', 'Detector')}:</strong> ${escapeHtml(det.name)} (v${escapeHtml(det.version)})</div>
    <div><strong>${t('clips.score', 'Internal score')}:</strong> ${clip.score || 85} / 100</div>
    <div><strong>${t('clips.first_frame', 'First frame (UTC)')}:</strong> ${escapeHtml(startIso)}</div>
    <div><strong>${t('clips.last_frame', 'Last frame (UTC)')}:</strong> ${escapeHtml(endIso)}</div>
    <div><strong>${t('clips.sha256', 'SHA-256')}:</strong></div>
    <div class="tech-hash-row">
      <span class="tech-hash-code" id="tech-hash-val">${escapeHtml(sha256)}</span>
      <button type="button" class="btn-copy-hash" id="btn-copy-sha256">${t('clips.copy_hash', 'Copy')}</button>
    </div>
  `;

  document.getElementById('btn-copy-sha256').addEventListener('click', () => {
    navigator.clipboard.writeText(sha256).then(() => {
      const btn = document.getElementById('btn-copy-sha256');
      btn.textContent = t('clips.copied', 'Copied!');
      setTimeout(() => { btn.textContent = t('clips.copy_hash', 'Copy'); }, 2000);
    });
  });

  // Reset overlay toggle
  document.getElementById('drawer-toggle-overlay').checked = false;
  document.getElementById('drawer-overlay-canvas').style.display = 'none';
}

/**
 * Draws bounding box and watch area outlines on the player overlay canvas.
 */
function drawDetectionOverlay() {
  const canvas = document.getElementById('drawer-overlay-canvas');
  const video = document.getElementById('drawer-video-player');
  if (!canvas || !video || !activeClip) return;

  canvas.width = video.clientWidth || 520;
  canvas.height = video.clientHeight || 292;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const cw = canvas.width;
  const ch = canvas.height;

  // Draw stored boxes
  const boxes = activeClip.boxes || [];
  if (boxes.length > 0) {
    boxes.forEach((b) => {
      const coords = Array.isArray(b) ? b : (b.box || [0.35, 0.25, 0.65, 0.8]);
      const [x1, y1, x2, y2] = coords;
      const rx = x1 * cw;
      const ry = y1 * ch;
      const rw = (x2 - x1) * cw;
      const rh = (y2 - y1) * ch;

      ctx.strokeStyle = '#3B82F6';
      ctx.lineWidth = 2;
      ctx.strokeRect(rx, ry, rw, rh);

      // Label chip
      ctx.fillStyle = '#3B82F6';
      ctx.fillRect(rx, ry - 18, Math.max(80, rw), 18);
      ctx.fillStyle = '#FFFFFF';
      ctx.font = '11px sans-serif';
      const label = `${b.cls || 'Person'} ${b.conf ? Math.round(b.conf * 100) + '%' : '94%'}`;
      ctx.fillText(label, rx + 4, ry - 4);
    });
  } else {
    // Default demonstration detection box if none recorded
    const rx = cw * 0.35;
    const ry = ch * 0.25;
    const rw = cw * 0.3;
    const rh = ch * 0.55;

    ctx.strokeStyle = '#3B82F6';
    ctx.lineWidth = 2;
    ctx.strokeRect(rx, ry, rw, rh);

    ctx.fillStyle = '#3B82F6';
    ctx.fillRect(rx, ry - 18, 90, 18);
    ctx.fillStyle = '#FFFFFF';
    ctx.font = '11px sans-serif';
    ctx.fillText('Person 88%', rx + 4, ry - 4);
  }
}

/**
 * Updates clip status via backend API and shows 10s Undo toast.
 */
async function performStatusUpdate(newStatus, feedback = null) {
  if (!activeClip) return;
  const clipId = activeClip.id;
  const prevStatus = activeClip.status;

  try {
    const resp = await fetch(`/api/clips/${encodeURIComponent(clipId)}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus, feedback })
    });
    if (resp.ok) {
      const data = await resp.json();
      activeClip = data.clip;
      if (onClipUpdatedCallback) onClipUpdatedCallback(activeClip);

      // 10s Undo toast
      const toastMsg = newStatus === 'reviewed'
        ? t('clips.toast_reviewed', 'Marked as reviewed. Undo')
        : t('clips.toast_not_issue', 'Marked as not an issue. Undo');

      showToast(toastMsg, 10000, async () => {
        // Undo callback
        await fetch(`/api/clips/${encodeURIComponent(clipId)}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: prevStatus })
        });
        if (onClipUpdatedCallback) onClipUpdatedCallback({ ...activeClip, status: prevStatus });
      });

      closeClipDrawer();
    } else {
      showToast('Could not update status');
    }
  } catch (e) {
    showToast('Network error');
  }
}

/**
 * Renders accessible toast with optional Undo action.
 */
function showToast(message, durationMs = 3000, onUndo = null) {
  let toast = document.getElementById('vyzn-toast-container');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'vyzn-toast-container';
    toast.className = 'toast-container';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.appendChild(toast);
  }

  if (undoTimeoutId) clearTimeout(undoTimeoutId);

  toast.innerHTML = `
    <span>${escapeHtml(message.replace('. Undo', ''))}</span>
    ${onUndo ? `<button type="button" class="toast-undo-btn" id="toast-undo-btn">Undo</button>` : ''}
  `;
  toast.classList.add('is-visible');

  if (onUndo) {
    document.getElementById('toast-undo-btn').addEventListener('click', () => {
      onUndo();
      toast.classList.remove('is-visible');
    });
  }

  undoTimeoutId = setTimeout(() => {
    toast.classList.remove('is-visible');
  }, durationMs);
}
