import { icons } from './icons.js';
import { escapeHtml } from '../utils.js';

/**
 * Renders a standardized tier badge (Alert, Review, Reviewed, Not an issue).
 * @param {'alert'|'review'|'reviewed'|'not_an_issue'} tier
 * @returns {string} HTML string
 */
export function renderTierBadge(tier) {
  let label = 'Review';
  let iconHtml = icons.review(14);
  let cssClass = 'review';

  switch (tier) {
    case 'alert':
      label = 'Alert';
      iconHtml = icons.alert(14);
      cssClass = 'alert';
      break;
    case 'review':
      label = 'Review';
      iconHtml = icons.review(14);
      cssClass = 'review';
      break;
    case 'reviewed':
      label = 'Reviewed';
      iconHtml = icons.check(14);
      cssClass = 'reviewed';
      break;
    case 'not_an_issue':
      label = 'Not an issue';
      iconHtml = icons.notAnIssue(14);
      cssClass = 'not-an-issue';
      break;
  }

  return `
    <span class="tier-badge ${cssClass}">
      ${iconHtml}
      <span>${escapeHtml(label)}</span>
    </span>
  `.trim();
}
