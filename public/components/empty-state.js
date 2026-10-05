import { renderButton } from './button.js';
import { escapeHtml } from '../utils.js';

/**
 * Renders an EmptyState component (line icon, single sentence, action button).
 * @param {object} props
 * @param {string} props.iconHtml - SVG string
 * @param {string} props.text - Single plain sentence
 * @param {string} [props.buttonLabel=''] - Optional button text
 * @param {string} [props.buttonId='']
 * @returns {string} HTML string
 */
export function renderEmptyState({ iconHtml, text, buttonLabel = '', buttonId = '' }) {
  const btn = buttonLabel ? renderButton({ label: buttonLabel, variant: 'primary', id: buttonId }) : '';
  return `
    <div class="empty-state" role="region" aria-label="Empty state">
      <div class="empty-state-icon">
        ${iconHtml}
      </div>
      <p class="empty-state-text">${escapeHtml(text)}</p>
      ${btn}
    </div>
  `.trim();
}
