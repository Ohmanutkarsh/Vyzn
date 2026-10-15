import { renderTierBadge } from './tier-badge.js';
import { icons } from './icons.js';
import { formatWhen, formatLeft, escapeHtml } from '../utils.js';

/**
 * Computes plain-language headline from title or reasons[0] per Section 6.3 headline table.
 */
function resolveHeadline(clip) {
  if (clip.title) return clip.title;
  if (clip.headline) return clip.headline;
  if (clip.reasons && clip.reasons.length > 0) {
    const r = clip.reasons[0];
    const code = r.code;
    const params = r.params || {};
    const area = params.area || clip.areaName || 'Cash counter';
    if (code === 'entered_restricted_area') return `Person entered ${area}`;
    if (code === 'stayed_in_area') return `Person stayed ${params.duration || (params.seconds ? `${params.seconds} seconds` : '63 seconds')} in ${area}`;
    if (code === 'outside_shop_hours') return 'Movement outside shop hours';
    if (code === 'person_detected') return `Person in ${area}`;
    if (code === 'movement') return `Movement in ${area}`;
  }
  return 'Person stayed in area';
}

function resolveTriggerText(clip) {
  const tr = clip.triggerReason || clip.trigger_reason;
  if (!tr) return '';
  const clean = tr.replace(/_/g, ' ');
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

// This helper function creates the visual tick bar at the bottom of each thumbnail.
// It colors high-activity moments yellow/red and quiet moments soft grey so you can see event timing at a glance.
function renderTickTrack(clip, durSec) {
  // Grab the event timeline intervals if available
  const intervals = clip.timelineIntervals || clip.timeline_intervals || [];
  const dur = Math.max(1, durSec || 15);

  let segmentsHtml = '';
  if (intervals.length > 0) {
    // Convert each 3-second tick window into a colored stripe on the mini timeline
    segmentsHtml = intervals.map(item => {
      const start = item.start_sec !== undefined ? item.start_sec : (item.startSec || 0);
      const end = item.end_sec !== undefined ? item.end_sec : (item.endSec || start + 3);
      const leftPct = Math.min(100, Math.max(0, (start / dur) * 100));
      const widthPct = Math.min(100 - leftPct, Math.max(1.5, ((end - start) / dur) * 100));
      const isEvent = item.type === 'event' || (item.score && item.score >= 30);
      const color = isEvent ? ((item.score && item.score >= 70) ? '#ef4444' : '#f59e0b') : 'rgba(255,255,255,0.12)';
      return `<span class="clip-tick-segment" title="${escapeHtml(item.label || '')}" style="position: absolute; left: ${leftPct.toFixed(1)}%; width: ${widthPct.toFixed(1)}%; height: 100%; background: ${color};"></span>`;
    }).join('');
  } else if (clip.timeline && clip.timeline.length > 0) {
    // If intervals are not present, fallback to individual event marker dots
    segmentsHtml = clip.timeline.map(ev => {
      const offset = ev.offset_sec || 0;
      const leftPct = Math.min(98, Math.max(0, (offset / dur) * 100));
      const color = (ev.score && ev.score >= 70) ? '#ef4444' : '#38bdf8';
      return `<span class="clip-tick-marker" style="position: absolute; left: ${leftPct.toFixed(1)}%; width: 3px; height: 100%; background: ${color};"></span>`;
    }).join('');
  }

  // Return the complete bar along with a glowing blue playhead dot that moves as the video plays
  return `
    <div class="clip-seek-track" style="position: absolute; bottom: 0; left: 0; right: 0; height: 5px; background: rgba(0,0,0,0.5); z-index: 2; display: flex; overflow: hidden; pointer-events: none;">
      ${segmentsHtml}
      <span class="clip-playhead-marker" style="position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: #38bdf8; z-index: 3; transition: left 0.1s linear;"></span>
    </div>
  `;
}

/**
 * Renders a ClipCard component for the Clips gallery (Section 6.3).
 * @param {object} props
 * @param {object} props.clip
 * @returns {string} HTML string
 */
export function renderClipCard({ clip }) {
  // URLs for thumbnail snapshot, poster image, and inline short preview video
  const thumbUrl = clip.thumbnailUrl || '/static/img/placeholder.jpg';
  const posterUrl = clip.posterUrl || (clip.urls && clip.urls.poster) || thumbUrl;
  const previewUrl = clip.previewUrl || (clip.urls && clip.urls.preview) || '';

  // Calculate clip duration in minutes and seconds for the badge
  const durSec = clip.durationSec || Math.round((clip.endMs - clip.startMs) / 1000) || 15;
  const durMin = Math.floor(durSec / 60);
  const durRem = Math.floor(durSec % 60);
  const durationStr = `${durMin}:${durRem < 10 ? '0' : ''}${durRem}`;

  const headline = resolveHeadline(clip);
  const locationStr = `${escapeHtml(clip.cameraName || clip.cameraId)}${clip.areaName ? ` · ${escapeHtml(clip.areaName)}` : ''}`;
  const whenStr = formatWhen(clip.startMs || clip.triggerMs);
  const leftStr = formatLeft(clip.expiresAtMs);

  // Reviewed and Not-an-issue cards show the grey status icon and word instead of the tier colour (Section 6.3)
  const badgeHtml = (clip.status === 'reviewed' || clip.status === 'not_an_issue')
    ? renderTierBadge(clip.status)
    : renderTierBadge(clip.tier);

  // Shows if this clip is part of a longer split event (Part 1, Part 2, etc.)
  const partIdx = clip.partIndex !== undefined ? clip.partIndex : (clip.part_index || 0);
  const isMultiPart = Boolean(clip.parentEventId || clip.parent_event_id || partIdx > 0);
  const partBadge = isMultiPart ? `<span class="clip-part-indicator" style="background: rgba(14, 165, 233, 0.9); color: #fff; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">Part ${partIdx + 1}</span>` : '';

  // Trigger reason tag (e.g. Movement, Person Entered)
  const trigText = resolveTriggerText(clip);
  const trigChip = trigText ? `<span class="clip-reason-chip" style="display: inline-block; font-size: 11px; padding: 2px 7px; border-radius: 4px; background: rgba(255,255,255,0.07); color: var(--text-2); margin-top: 4px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">🎯 ${escapeHtml(trigText)}</span>` : '';

  // Small blue chips showing detected object types (Person, Vehicle, etc.)
  const objects = clip.objects || [];
  const objList = objects.map(o => (typeof o === 'string' ? o : (o.cls || o.class_name || ''))).filter(Boolean).slice(0, 3);
  const objChips = objList.length > 0 ? objList.map(o => `<span class="clip-obj-chip" style="display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; background: rgba(56, 189, 248, 0.12); color: #38bdf8; margin-right: 4px;">${escapeHtml(o)}</span>`).join('') : '';

  // One-line summary of what happened
  const summarySnippet = (clip.oneLineSummary || clip.one_line_summary || clip.summary) ? `<p class="clip-summary-text" style="font-size: 12px; color: var(--text-3); margin: 2px 0 0 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.35;">${escapeHtml(clip.oneLineSummary || clip.one_line_summary || clip.summary)}</p>` : '';

  // Assemble the full HTML card with video preview and bottom seek bar
  return `
    <article class="clip-card" data-clip-id="${escapeHtml(clip.id)}" tabindex="0" role="button" aria-label="${escapeHtml(headline)} at ${escapeHtml(locationStr)}">
      <div class="clip-thumb-frame" style="position: relative; overflow: hidden; background: #000;">
        <div class="clip-badge-top-left" style="display: flex; align-items: center; z-index: 3;">
          ${badgeHtml}
          ${partBadge}
        </div>
        <img class="clip-thumb-img" src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(headline)}" loading="lazy" />
        ${previewUrl ? `
          <video class="clip-inline-preview"
                 data-src="${escapeHtml(previewUrl)}"
                 poster="${escapeHtml(posterUrl)}"
                 muted
                 loop
                 playsinline
                 preload="none"
                 style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; transition: opacity 0.25s ease; z-index: 1;">
          </video>
        ` : ''}
        ${renderTickTrack(clip, durSec)}
        <span class="clip-duration-bottom-right" style="z-index: 3;">${durationStr}</span>
      </div>
      <div class="clip-info-body">
        <h3 class="clip-headline">${escapeHtml(headline)}</h3>
        ${summarySnippet}
        <p class="clip-subline">${locationStr}</p>
        <p class="clip-time">${escapeHtml(whenStr)}</p>
        ${trigChip ? `<div>${trigChip}</div>` : ''}
        ${objChips ? `<div style="margin-top: 4px; display: flex; flex-wrap: wrap; gap: 2px;">${objChips}</div>` : ''}
        ${leftStr ? `
          <div class="clip-deletes">
            ${icons.clock(13)}
            <span>Deletes in ${escapeHtml(leftStr)}</span>
          </div>
        ` : ''}
      </div>
    </article>
  `.trim();
}
