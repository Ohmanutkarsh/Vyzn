import { renderTierBadge } from './tier-badge.js';
import { icons } from './icons.js';
import { formatWhen, formatLeft, escapeHtml } from '../utils.js';

/**
 * Computes plain-language headline from reasons[0] per Section 6.3 headline table.
 */
function resolveHeadline(clip) {
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

  return `
    <article class="clip-card" data-clip-id="${escapeHtml(clip.id)}" tabindex="0" role="button" aria-label="${escapeHtml(headline)} at ${escapeHtml(locationStr)}">
      <div class="clip-thumb-frame">
        <div class="clip-badge-top-left">
          ${badgeHtml}
        </div>
        <img class="clip-thumb-img" src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(headline)}" loading="lazy" />
        <span class="clip-duration-bottom-right">${durationStr}</span>
      </div>
      <div class="clip-info-body">
        <h3 class="clip-headline">${escapeHtml(headline)}</h3>
        <p class="clip-subline">${locationStr}</p>
        <p class="clip-time">${escapeHtml(whenStr)}</p>
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
