import { renderTierBadge } from './tier-badge.js';
import { renderButton } from './button.js';
import { formatWhen, escapeHtml } from '../utils.js';

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
 * Renders a FlagRow component for the Flags panel on Overview.
 * @param {object} props
 * @param {object} props.clip - Clip object from backend
 * @returns {string} HTML string
 */
export function renderFlagRow({ clip }) {
  const thumbUrl = clip.thumbnailUrl || '/static/img/placeholder.jpg';
  const headline = resolveHeadline(clip);
  const whenStr = formatWhen(clip.startMs || clip.triggerMs);
  const locationStr = `${escapeHtml(clip.cameraName || clip.cameraId)}${clip.areaName ? ` · ${escapeHtml(clip.areaName)}` : ''}`;

  const durSec = clip.durationSec || Math.round((clip.endMs - clip.startMs) / 1000) || 15;
  const durMin = Math.floor(durSec / 60);
  const durRem = Math.floor(durSec % 60);
  const durationStr = `${durMin}:${durRem < 10 ? '0' : ''}${durRem}`;

  const badgeHtml = (clip.status === 'reviewed' || clip.status === 'not_an_issue')
    ? renderTierBadge(clip.status)
    : renderTierBadge(clip.tier);

  return `
    <div class="flag-row" data-clip-id="${escapeHtml(clip.id)}" role="button" tabindex="0">
      <div class="flag-thumb-frame">
        <img class="flag-thumb-img" src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(headline)}" loading="lazy" />
        <span class="flag-thumb-duration">${durationStr}</span>
      </div>
      <div class="flag-content">
        <div style="margin-bottom: 3px;">
          ${badgeHtml}
        </div>
        <div class="flag-headline" title="${escapeHtml(headline)}">
          ${escapeHtml(headline)}
        </div>
        <div class="flag-meta">
          <span>${locationStr}</span>
          <span>·</span>
          <span>${escapeHtml(whenStr)}</span>
        </div>
      </div>
      <div class="flag-actions">
        ${renderButton({ label: 'Open', variant: 'primary', className: 'btn-open-flag' })}
        ${renderButton({ label: 'Not an issue', variant: 'quiet', className: 'btn-dismiss-flag' })}
      </div>
    </div>
  `.trim();
}
