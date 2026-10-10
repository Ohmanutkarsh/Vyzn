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

/**
 * Renders a ClipCard component for the Clips gallery (Section 6.3).
 * @param {object} props
 * @param {object} props.clip
 * @returns {string} HTML string
 */
export function renderClipCard({ clip }) {
  const thumbUrl = clip.thumbnailUrl || '/static/img/placeholder.jpg';
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

  const partIdx = clip.partIndex !== undefined ? clip.partIndex : (clip.part_index || 0);
  const isMultiPart = Boolean(clip.parentEventId || clip.parent_event_id || partIdx > 0);
  const partBadge = isMultiPart ? `<span class="clip-part-indicator" style="background: rgba(14, 165, 233, 0.9); color: #fff; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">Part ${partIdx + 1}</span>` : '';

  const trigText = resolveTriggerText(clip);
  const trigChip = trigText ? `<span class="clip-reason-chip" style="display: inline-block; font-size: 11px; padding: 2px 7px; border-radius: 4px; background: rgba(255,255,255,0.07); color: var(--text-2); margin-top: 4px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">🎯 ${escapeHtml(trigText)}</span>` : '';

  const objects = clip.objects || [];
  const objList = objects.map(o => (typeof o === 'string' ? o : (o.cls || o.class_name || ''))).filter(Boolean).slice(0, 3);
  const objChips = objList.length > 0 ? objList.map(o => `<span class="clip-obj-chip" style="display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; background: rgba(56, 189, 248, 0.12); color: #38bdf8; margin-right: 4px;">${escapeHtml(o)}</span>`).join('') : '';

  const summarySnippet = clip.summary ? `<p class="clip-summary-text" style="font-size: 12px; color: var(--text-3); margin: 2px 0 0 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.35;">${escapeHtml(clip.summary)}</p>` : '';

  return `
    <article class="clip-card" data-clip-id="${escapeHtml(clip.id)}" tabindex="0" role="button" aria-label="${escapeHtml(headline)} at ${escapeHtml(locationStr)}">
      <div class="clip-thumb-frame">
        <div class="clip-badge-top-left" style="display: flex; align-items: center;">
          ${badgeHtml}
          ${partBadge}
        </div>
        <img class="clip-thumb-img" src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(headline)}" loading="lazy" />
        <span class="clip-duration-bottom-right">${durationStr}</span>
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
